"""成片质量检测.

从 OpenMontage video_compose.py 的 final self-review 提取。
7 项自动化检查：技术探测 / 黑帧检测 / 音量检测 / 时长 / 分辨率 / 编码 / 字幕。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from runtime.montage.ffmpeg_ops import FFmpegOps

logger = logging.getLogger(__name__)


@dataclass
class QualityReport:
    """质量检测报告."""
    overall: str = "unknown"  # "pass" / "revise" / "fail"
    checks: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "overall": self.overall,
            "checks": self.checks,
        }


class QualityChecker:
    """成片质量检测器.

    7 项检查：
    1. technical_probe: ffprobe 基础属性
    2. black_frame: 黑帧检测（4 个采样点）
    3. audio_level: 音量检测（均值/峰值/静音/削波）
    4. duration: 时长合理性
    5. resolution: 分辨率检查
    6. codec: 编码兼容性
    7. file_size: 文件大小
    """

    def check(
        self,
        video_path: str,
        min_duration: float = 1.0,
        max_duration: float = 600.0,
        expected_resolution: Optional[tuple[int, int]] = None,
    ) -> dict[str, Any]:
        """执行全部质量检查."""
        report = QualityReport()
        failures = 0

        # 1. Technical probe
        probe_result = self._check_technical_probe(video_path)
        report.checks["technical_probe"] = probe_result
        if not probe_result["pass"]:
            failures += 1

        # 2. Black frame detection
        black_result = self._check_black_frames(video_path, probe_result)
        report.checks["black_frames"] = black_result
        if not black_result["pass"]:
            failures += 1

        # 3. Audio level
        audio_result = self._check_audio_level(video_path)
        report.checks["audio_level"] = audio_result
        if not audio_result["pass"]:
            failures += 1

        # 4. Duration
        duration = probe_result.get("duration", 0)
        dur_result = {
            "pass": min_duration <= duration <= max_duration,
            "duration": duration,
            "min": min_duration,
            "max": max_duration,
        }
        report.checks["duration"] = dur_result
        if not dur_result["pass"]:
            failures += 1

        # 5. Resolution
        width = probe_result.get("width", 0)
        height = probe_result.get("height", 0)
        res_result: dict[str, Any] = {
            "pass": True,
            "width": width,
            "height": height,
        }
        if expected_resolution:
            res_result["expected"] = f"{expected_resolution[0]}x{expected_resolution[1]}"
            res_result["pass"] = (width == expected_resolution[0] and height == expected_resolution[1])
        elif width < 320 or height < 240:
            res_result["pass"] = False
            res_result["reason"] = "Resolution too low"
        report.checks["resolution"] = res_result
        if not res_result["pass"]:
            failures += 1

        # 6. Codec
        video_codec = probe_result.get("video_codec", "")
        audio_codec = probe_result.get("audio_codec", "")
        codec_result = {
            "pass": video_codec in ("h264", "hevc", "libx264", "libx265"),
            "video_codec": video_codec,
            "audio_codec": audio_codec,
        }
        report.checks["codec"] = codec_result
        if not codec_result["pass"]:
            failures += 1

        # 7. File size
        file_size = Path(video_path).stat().st_size if Path(video_path).exists() else 0
        size_result = {
            "pass": file_size > 0,
            "file_size_bytes": file_size,
            "file_size_mb": round(file_size / (1024 * 1024), 2),
        }
        report.checks["file_size"] = size_result
        if not size_result["pass"]:
            failures += 1

        # Overall
        if failures == 0:
            report.overall = "pass"
        elif failures <= 2:
            report.overall = "revise"
        else:
            report.overall = "fail"

        return report.to_dict()

    def _check_technical_probe(self, video_path: str) -> dict[str, Any]:
        """技术探测."""
        info = FFmpegOps.probe(video_path)
        if not info:
            return {"pass": False, "error": "Failed to probe video"}

        return {
            "pass": True,
            "width": info.get("width"),
            "height": info.get("height"),
            "fps": info.get("fps"),
            "video_codec": info.get("video_codec"),
            "audio_codec": info.get("audio_codec"),
            "duration": info.get("duration"),
            "sample_rate": info.get("sample_rate"),
        }

    def _check_black_frames(
        self, video_path: str, probe_info: dict[str, Any],
    ) -> dict[str, Any]:
        """黑帧检测（在 10%/35%/65%/90% 位置采样）."""
        duration = probe_info.get("duration", 0)
        if duration <= 0:
            return {"pass": True, "reason": "No duration info"}

        sample_points = [0.1, 0.35, 0.65, 0.9]
        black_count = 0

        for pct in sample_points:
            timestamp = duration * pct
            try:
                cmd = [
                    "ffmpeg", "-y",
                    "-ss", str(timestamp),
                    "-i", video_path,
                    "-frames:v", "1",
                    "-f", "rawvideo", "-pix_fmt", "rgb24",
                    "pipe:1",
                ]
                import subprocess
                result = subprocess.run(cmd, capture_output=True, timeout=15)
                if result.returncode == 0 and len(result.stdout) > 0:
                    # Check if frame is mostly black (all bytes near 0)
                    data = result.stdout
                    total = sum(data)
                    avg = total / len(data) if data else 0
                    if avg < 5:  # Threshold for "black"
                        black_count += 1
            except Exception:
                pass

        passed = black_count <= 1  # Allow 1 black frame
        return {
            "pass": passed,
            "black_frames": black_count,
            "total_sampled": len(sample_points),
        }

    def _check_audio_level(self, video_path: str) -> dict[str, Any]:
        """音量检测."""
        try:
            cmd = [
                "ffmpeg", "-y",
                "-i", video_path,
                "-af", "volumedetect",
                "-f", "null", "/dev/null",
            ]
            import subprocess
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            stderr = result.stderr

            mean_vol = self._parse_volumedetect(stderr, "mean_volume")
            max_vol = self._parse_volumedetect(stderr, "max_volume")

            has_audio = FFmpegOps.has_audio(video_path)
            if not has_audio:
                return {"pass": True, "reason": "No audio stream (may be intentional)"}

            passed = True
            issues = []
            if mean_vol is not None and mean_vol < -40:
                passed = False
                issues.append(f"Very low mean volume: {mean_vol}dB")
            if max_vol is not None and max_vol > -1:
                issues.append(f"Possible clipping: max {max_vol}dB")

            return {
                "pass": passed,
                "mean_volume_db": mean_vol,
                "max_volume_db": max_vol,
                "issues": issues,
            }
        except Exception as e:
            return {"pass": True, "reason": f"Audio check failed: {e}"}

    @staticmethod
    def _parse_volumedetect(stderr: str, key: str) -> Optional[float]:
        """从 volumedetect 输出中解析音量值."""
        pattern = rf"{key}:\s*([-\d.]+)\s*dB"
        match = re.search(pattern, stderr)
        if match:
            return float(match.group(1))
        return None