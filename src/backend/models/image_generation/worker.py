"""Makes the images for one request in its own process, then exits so the model's memory is fully released.

Reads a JSON job from stdin: {"modelPath", "prompt", "outputPaths", "inputPaths"}. With no inputPaths it generates one
image from the prompt. Otherwise each input is edited into the output at the same position.
"""

import json
import sys

from PIL import Image, UnidentifiedImageError

EXIT_INVALID_IMAGE = 2


def read_image(path):
    try:
        with Image.open(path) as image:
            image.load()
            return image.copy()
    except (UnidentifiedImageError, OSError):
        return None


def main():
    job = json.load(sys.stdin)
    # Checked first so a bad upload is rejected without waiting for PyTorch and the model to load.
    images = [read_image(path) for path in job["inputPaths"]]
    if any(image is None for image in images):
        return EXIT_INVALID_IMAGE

    from src.backend.models.image_generation import model

    if not images:
        model.generate(job["modelPath"], job["prompt"], job["outputPaths"][0])
        return 0

    fitted = [model.fit_image(image) for image in images]
    for image, path in zip(fitted, job["inputPaths"]):
        image.save(path, "PNG")
    model.edit_each(job["modelPath"], job["prompt"], list(zip(fitted, job["outputPaths"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
