"""Capability package."""
from runtime.v3.capability.registry import (
    CapabilityRegistry,
    Capability,
    # Text-to-Image
    DashscopeImageCapability,
    OpenAIImageCapability,
    MockImageCapability,
    # Image-to-Video
    KlingImageToVideoCapability,
    MockImageToVideoCapability,
    # TTS
    DashscopeTTSCapability,
    CosyVoiceCloudCapability,
    MockVoiceCapability,
    # Video & Storyboard
    MergeVideoCapability,
    GenerateStoryboardCapability,
    # Capability name constants
    CAP_GENERATE_IMAGE,
    CAP_IMAGE_TO_VIDEO,
    CAP_GENERATE_VOICE,
    CAP_MERGE_VIDEO,
    CAP_GENERATE_STORYBOARD,
)

__all__ = [
    "CapabilityRegistry",
    "Capability",
    "DashscopeImageCapability",
    "OpenAIImageCapability",
    "MockImageCapability",
    "KlingImageToVideoCapability",
    "MockImageToVideoCapability",
    "DashscopeTTSCapability",
    "CosyVoiceCloudCapability",
    "MockVoiceCapability",
    "MergeVideoCapability",
    "GenerateStoryboardCapability",
    "CAP_GENERATE_IMAGE",
    "CAP_IMAGE_TO_VIDEO",
    "CAP_GENERATE_VOICE",
    "CAP_MERGE_VIDEO",
    "CAP_GENERATE_STORYBOARD",
]