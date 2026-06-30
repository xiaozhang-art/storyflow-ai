"""SRT/VTT 字幕生成引擎.

从 OpenMontage tools/subtitle/subtitle_gen.py 提取，剥离 BaseTool 依赖。
支持词级时间轴对齐、自动断行、错别字纠正、多种高亮样式。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional


class SubtitleEngine:
    """字幕生成引擎.

    Usage:
        engine = SubtitleEngine()
        engine.generate(
            segments=[
                {
                    "start": 0.0, "end": 2.5,
                    "text": "Hello world this is a test",
                    "words": [
                        {"word": "Hello", "start": 0.0, "end": 0.4},
                        {"word": "world", "start": 0.5, "end": 0.8},
                    ],
                }
            ],
            output_path="output.srt",
        )
    """

    def generate(
        self,
        segments: list[dict[str, Any]],
        output_path: str,
        fmt: str = "srt",
        max_chars_per_line: int = 42,
        max_words_per_cue: int = 8,
        highlight_style: str = "none",
        corrections: Optional[dict[str, str]] = None,
    ) -> str:
        """生成字幕文件.

        Args:
            segments: 带时间戳的分段列表，每段包含:
                - start: 起始秒数
                - end: 结束秒数
                - text: 文本
                - words (可选): 词级时间戳 [{word, start, end}]
            output_path: 输出文件路径
            fmt: "srt" / "vtt" / "json"
            max_chars_per_line: 每行最大字符数
            max_words_per_cue: 每条字幕最大词数
            highlight_style: "none" / "word_by_word" / "karaoke"
            corrections: 词级纠正映射 {错词: 正词}

        Returns:
            输出文件路径
        """
        if corrections:
            segments = self._apply_corrections(segments, corrections)

        cues = self._build_cues(segments, max_words_per_cue, max_chars_per_line)

        if fmt == "srt":
            content = self._render_srt(cues, highlight_style)
            ext = ".srt"
        elif fmt == "vtt":
            content = self._render_vtt(cues, highlight_style)
            ext = ".vtt"
        elif fmt == "json":
            content = json.dumps(
                {"cues": cues, "highlight_style": highlight_style}, indent=2
            )
            ext = ".caption.json"
        else:
            raise ValueError(f"Unknown format: {fmt}")

        if not output_path.endswith(ext):
            output_path = str(Path(output_path).with_suffix(ext))

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(content, encoding="utf-8")

        return str(out)

    def generate_from_dialogues(
        self,
        dialogues: list[dict[str, Any]],
        audio_durations: dict[int, float],
        output_path: str,
        fmt: str = "srt",
    ) -> str:
        """从对话列表生成字幕（无词级时间戳，按场景时长分配）.

        这是 StoryFlow 特化的便捷方法。dialogues 格式与 storyboard 场景对齐。

        Args:
            dialogues: [{scene_no, dialogue, characters?}, ...]
            audio_durations: {scene_no: duration_seconds}
            output_path: 输出文件路径
            fmt: 字幕格式

        Returns:
            输出文件路径
        """
        segments = []
        cumulative = 0.0

        for d in sorted(dialogues, key=lambda x: x.get("scene_no", 0)):
            scene_no = d.get("scene_no", 0)
            dialogue = d.get("dialogue", "")
            if not dialogue.strip():
                cumulative += audio_durations.get(scene_no, 5.0)
                continue

            duration = audio_durations.get(scene_no, 5.0)
            segments.append({
                "start": cumulative,
                "end": cumulative + duration,
                "text": dialogue,
            })
            cumulative += duration

        return self.generate(segments, output_path, fmt=fmt, max_words_per_cue=8)

    # ---- 内部方法 ----

    @staticmethod
    def _apply_corrections(
        segments: list[dict], corrections: dict[str, str],
    ) -> list[dict]:
        """应用词级纠正."""
        import copy
        corr = {k.lower(): v for k, v in corrections.items()}
        result = copy.deepcopy(segments)

        for seg in result:
            words = seg.get("words", [])
            for w in words:
                raw = w.get("word", "").strip()
                stripped = raw.lower().rstrip(".,!?;:'\"")
                if stripped in corr:
                    trailing = raw[len(stripped):]
                    w["word"] = corr[stripped] + trailing
            if "text" in seg and words:
                seg["text"] = " ".join(w["word"] for w in words)
            elif "text" in seg:
                for wrong, right in corr.items():
                    seg["text"] = re.sub(
                        r"\b" + re.escape(wrong) + r"\b",
                        right, seg["text"], flags=re.IGNORECASE,
                    )
        return result

    def _build_cues(
        self, segments: list[dict], max_words: int, max_chars: int,
    ) -> list[dict]:
        """将词分组为显示字幕条目."""
        all_words: list[dict] = []

        for seg in segments:
            words = seg.get("words", [])
            if words:
                all_words.extend(words)
            elif "text" in seg:
                all_words.append({
                    "word": seg["text"],
                    "start": seg["start"],
                    "end": seg["end"],
                })

        if not all_words:
            return []

        cues = []
        buf: list[dict] = []
        buf_text = ""

        for w in all_words:
            word_text = w["word"].strip()
            candidate = f"{buf_text} {word_text}".strip() if buf_text else word_text

            if buf and (len(buf) >= max_words or len(candidate) > max_chars):
                cues.append(self._flush_buf(buf, buf_text, cues))
                buf = []
                buf_text = ""

            buf.append(w)
            buf_text = f"{buf_text} {word_text}".strip() if buf_text else word_text

        if buf:
            cues.append(self._flush_buf(buf, buf_text, cues))

        return cues

    @staticmethod
    def _flush_buf(buf: list[dict], buf_text: str, cues: list[dict]) -> dict:
        return {
            "index": len(cues) + 1,
            "start": buf[0]["start"],
            "end": buf[-1]["end"],
            "text": buf_text,
            "words": [
                {"word": b["word"].strip(), "start": b["start"], "end": b["end"]}
                for b in buf
            ],
        }

    def _render_srt(self, cues: list[dict], highlight_style: str = "none") -> str:
        """渲染 SRT 格式."""
        lines: list[str] = []

        if highlight_style == "word_by_word":
            idx = 1
            for cue in cues:
                for wi in cue.get("words", []):
                    lines.append(str(idx))
                    lines.append(f"{self._ts_srt(wi['start'])} --> {self._ts_srt(wi['end'])}")
                    lines.append(wi["word"])
                    lines.append("")
                    idx += 1
        elif highlight_style == "karaoke":
            for cue in cues:
                words = cue.get("words", [])
                if not words:
                    lines.append(str(cue["index"]))
                    lines.append(f"{self._ts_srt(cue['start'])} --> {self._ts_srt(cue['end'])}")
                    lines.append(cue["text"])
                    lines.append("")
                    continue
                for wi, w in enumerate(words):
                    lines.append(str(cue["index"] * 100 + wi))
                    lines.append(f"{self._ts_srt(w['start'])} --> {self._ts_srt(w['end'])}")
                    parts = []
                    for wj, ww in enumerate(words):
                        if wj == wi:
                            parts.append(f"<b>{ww['word']}</b>")
                        else:
                            parts.append(ww["word"])
                    lines.append(" ".join(parts))
                    lines.append("")
        else:
            for cue in cues:
                lines.append(str(cue["index"]))
                lines.append(f"{self._ts_srt(cue['start'])} --> {self._ts_srt(cue['end'])}")
                lines.append(cue["text"])
                lines.append("")

        return "\n".join(lines)

    def _render_vtt(self, cues: list[dict], highlight_style: str = "none") -> str:
        """渲染 VTT 格式."""
        lines = ["WEBVTT", ""]

        if highlight_style == "word_by_word":
            for cue in cues:
                for wi in cue.get("words", []):
                    lines.append(f"{self._ts_vtt(wi['start'])} --> {self._ts_vtt(wi['end'])}")
                    lines.append(wi["word"])
                    lines.append("")
        elif highlight_style == "karaoke":
            for cue in cues:
                words = cue.get("words", [])
                if not words:
                    lines.append(f"{self._ts_vtt(cue['start'])} --> {self._ts_vtt(cue['end'])}")
                    lines.append(cue["text"])
                    lines.append("")
                    continue
                for wi, w in enumerate(words):
                    lines.append(f"{self._ts_vtt(w['start'])} --> {self._ts_vtt(w['end'])}")
                    parts = []
                    for wj, ww in enumerate(words):
                        if wj == wi:
                            parts.append(f"<b>{ww['word']}</b>")
                        else:
                            parts.append(ww["word"])
                    lines.append(" ".join(parts))
                    lines.append("")
        else:
            for cue in cues:
                lines.append(f"{self._ts_vtt(cue['start'])} --> {self._ts_vtt(cue['end'])}")
                lines.append(cue["text"])
                lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _ts_srt(seconds: float) -> str:
        """SRT 时间戳: HH:MM:SS,mmm"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int(round((seconds % 1) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    @staticmethod
    def _ts_vtt(seconds: float) -> str:
        """VTT 时间戳: HH:MM:SS.mmm"""
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int(round((seconds % 1) * 1000))
        return f"{h:02d}:{m:02d}:{s:02d}.{ms:03d}"