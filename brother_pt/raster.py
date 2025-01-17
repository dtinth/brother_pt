"""
   Copyright 2022 Thomas Reidemeister

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.
"""
from PIL import Image
from .cmd import MediaWidthToTapeMargin, PRINT_HEAD_PINS


# FIXME: test
def make_fit(image: Image, media_width: int):
    expected_height = MediaWidthToTapeMargin.to_print_width(media_width)
    if image.height != expected_height:
        if image.width != expected_height:
            return None
        else:
            return image.transpose(Image.ROTATE_90)
    return image


def has_transparency(img):
    if img.info.get("transparency", None) is not None:
        return True
    if img.mode == "P":
        transparent = img.info.get("transparency", -1)
        for _, index in img.getcolors():
            if index == transparent:
                return True


def select_raster_channel(image: Image):
    # Special handling for paletized images
    if image.mode == 'P':
        if has_transparency(image):
            image = image.convert('RGBA')
        else:
            image = image.convert('RGB')

    if image.mode == '1':
        # BW
        return image
    elif image.mode == 'L':
        # Use white as indication for background
        return image.point(lambda x: 0xFF if x < 0xFF else 0)
    elif image.mode == 'RGB' or image.mode == 'RGBA':
        # Use white as indication for background
        return image.convert('L').point(lambda x: 0xFF if x < 0x80 else 0)
    else:
        raise AttributeError("Unsupported color space for printing: "+image.mode)


# FIXME: Test
def compress_buffer(buffer: bytearray):
    # Compress bytes to bit
    bits = bytearray()
    for i in range(0, len(buffer), 8):
        byte = 0

        for j in range(0, 8):
            value = buffer[i + j]

            if value > 0:
                byte |= (1 << (7 - j))

        bits.append(byte)
    return bits


def prepare_image(image: Image, media_width: int):
    width, height = image.width, image.height
    image = make_fit(image, media_width)
    # Image doesn't fit the tape width
    if image is None:
        # FIXME: provide option for scaling
        expected_height = MediaWidthToTapeMargin.to_print_width(media_width)
        raise AttributeError("At least one dimension needs to fit the tape width: %i vs (%i, %i)" %
                             (expected_height, width, height))

    return select_raster_channel(image)


def raster_image(prepared_image: Image, media_width: int):
    # Print buffer
    buffer = bytearray()

    # Compose raster template
    for column in range(prepared_image.width):
        # Leading margin of print head
        buffer += b'\x00'*MediaWidthToTapeMargin.margin[media_width]

        # printable raster
        for row in range(prepared_image.height):
            buffer += b'\xFF' if prepared_image.getpixel((column, row)) else b'\00'

        # Trailing margin of print head
        buffer += b'\x00' * MediaWidthToTapeMargin.margin[media_width]

    return compress_buffer(buffer)
