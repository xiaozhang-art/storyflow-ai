"""Capability package."""
from runtime.v3.capability.registry import (
    CapabilityRegistry,
    Capability,
    GenerateImageCapability,
    GenerateVoiceCapability,
    MergeVideoCapability,
    GenerateStoryboardCapability,
    CAP_GENERATE_IMAGE,
    CAP_GENERATE_VOICE,
    CAP_MERGE_VIDEO,
    CAP_GENERATE_STORYBOARD,
    CAP_UPSCALE,
    CAP_INPAINT,
    CAP_FACE_REPAIR,
)

__all__ = [
    "CapabilityRegistry",
    "Capability",
    "GenerateImageCapability",
    "GenerateVoiceCapability",
    "MergeVideoCapability",
    "GenerateStoryboardCapability",
    "CAP_GENERATE_IMAGE",
    "CAP_GENERATE_VOICE",
    "CAP_MERGE_VIDEO",
    "CAP_GENERATE_STORYBOARD",
    "CAP_UPSCALE",
    "CAP_INPAINT",
    "CAP_FACE_REPAIR",
]