"""Runs the image model with Diffusers. Only the worker process imports this, because PyTorch is large."""

import torch
from diffusers import StableDiffusionXLImg2ImgPipeline, StableDiffusionXLPipeline
from PIL import Image, ImageOps

STEPS = 25
EDIT_STRENGTH = 0.6
MAX_IMAGE_SIDE = 1024
SIZE_MULTIPLE = 8


def load_pipeline(pipeline_class, model_path):
    pipeline = pipeline_class.from_single_file(model_path, torch_dtype=torch.float16, use_safetensors=True)
    pipeline.to("mps" if torch.backends.mps.is_available() else "cpu")
    pipeline.enable_attention_slicing()
    pipeline.vae.enable_tiling()
    return pipeline


def fit_image(image):
    """Upright RGB, longest side at most MAX_IMAGE_SIDE, with both sides a size the model accepts."""
    image = ImageOps.exif_transpose(image).convert("RGB")
    scale = min(1, MAX_IMAGE_SIDE / max(image.size))
    width, height = (max(SIZE_MULTIPLE, int(side * scale) // SIZE_MULTIPLE * SIZE_MULTIPLE) for side in image.size)
    return image.resize((width, height), Image.Resampling.LANCZOS)


def generate(model_path, prompt, output_path):
    pipeline = load_pipeline(StableDiffusionXLPipeline, model_path)
    pipeline(prompt=prompt, num_inference_steps=STEPS).images[0].save(output_path, "PNG")


def edit_each(model_path, prompt, images_and_outputs):
    """Loads the model once, then edits each image with the same prompt."""
    pipeline = load_pipeline(StableDiffusionXLImg2ImgPipeline, model_path)
    for image, output_path in images_and_outputs:
        result = pipeline(prompt=prompt, image=image, strength=EDIT_STRENGTH, num_inference_steps=STEPS).images[0]
        result.save(output_path, "PNG")
