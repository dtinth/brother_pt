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
import sys

import usb.core
import usb.util
import warnings

from .cmd import *
from .raster import *


def find_printers(serial=None):
    found_printers = []
    for product_id in SupportedPrinterIDs:
        dev = usb.core.find(idVendor=USBID_BROTHER, idProduct=product_id)
        if dev is not None:
            if serial is not None:
                if serial == dev.serial_number:
                    found_printers.append(dev)
                else:
                    continue
            else:
                found_printers.append(dev)

    return found_printers


class BrotherPt:
    def __init__(self, serial: str = None):
        printers = find_printers(serial)
        if len(printers) == 0:
            raise RuntimeError("No supported driver found")

        self._media_width = None
        self._media_type = None
        self._tape_color = None
        self._text_color = None

        self._dev = printers[0]
        self.__initialize()

    def __initialize(self):
        # libusb initialization, and bypass kernel drivers
        if self._dev.is_kernel_driver_active(0):
            self._dev.detach_kernel_driver(0)

        self._dev.set_configuration()
        self.update_status()

    def __del__(self):
        usb.util.dispose_resources(self._dev)

    def __write(self, data: bytes) -> int:
        length = 0
        while length < len(data):
            # chunk into packet size
            length += self._dev.write(USB_OUT_EP_ID, data[length:(length+0x40)], USB_TRX_TIMEOUT_MS)
            if length == 0:
                raise RuntimeError("IO timeout while writing to printer")
        return length

    def __read(self, length: int = 0x80) -> bytes:
        try:
            data = self._dev.read(USB_IN_EP_ID, length, USB_TRX_TIMEOUT_MS)
        except usb.core.USBError as e:
            raise RuntimeError("IO timeout while reading from printer")
        return data

    def update_status(self):
        self.__write(invalidate())
        self.__write(initialize())
        status_information = b''
        while len(status_information) == 0:
            self.__write(status_information_request())
            status_information = self.__read(STATUS_MESSAGE_LENGTH)

        self._media_width = status_information[StatusOffsets.MEDIA_WIDTH]
        self._media_type = MediaType(status_information[StatusOffsets.MEDIA_TYPE])
        self._tape_color = TapeColor(status_information[StatusOffsets.TAPE_COLOR_INFORMATION])
        self._text_color = TextColor(status_information[StatusOffsets.TEXT_COLOR_INFORMATION])

    @property
    def media_width(self) -> int:
        return self._media_width

    @property
    def media_type(self) -> MediaType:
        return self._media_type

    @property
    def tape_color(self) -> TapeColor:
        return self._tape_color

    @property
    def text_color(self) -> TextColor:
        return self._text_color

    def print_data(self, data:bytes, margin_px:int, is_last_page:bool=True):
        self.__write(enter_dynamic_command_mode())
        self.__write(enable_status_notification())
        self.__write(print_information(data, self.media_width))
        self.__write(set_mode())
        self.__write(set_advanced_mode())
        self.__write(margin_amount(margin_px))
        self.__write(set_compression_mode())
        for cmd in gen_raster_commands(data):
            self.__write(cmd)

        # Send 6 blank lines to ensure the printer finishes the print job
        # (This gets image aligned properly in P710BT)
        for _ in range(6):
            self.__write(b'\x5A')

        if is_last_page:
            self.__write(print_with_feeding())
        else:
            self.__write(print_without_feeding())
        while True:
            res = self.__read()
            if len(res) > 0:
                if res[StatusOffsets.STATUS_TYPE] == StatusType.PRINTING_COMPLETED:
                    # absorb phase change message
                    self.__read()
                    break
                elif res[StatusOffsets.STATUS_TYPE] == StatusType.ERROR_OCCURRED:
                    error_message = ''
                    if res[8]: # Error 1
                        if res[8] & 0x01:
                            error_message += 'no media|'
                        if res[8] & 0x04:
                            error_message += 'cutter jam|'
                        if res[8] & 0x08:
                            error_message += 'low batteries|'
                        if res[8] & 0x40:
                            error_message += 'high-voltage adapter|'
                        pass
                    if res[9]: # Error 2
                        if res[9] & 0x01:
                            error_message += 'wrong media (check size)|'
                        if res[9] & 0x10:
                            error_message += 'cover open|'
                        if res[9] & 0x20:
                            error_message += 'overheating|'
                    if len(error_message) > 0:
                        error_message = error_message[:-1]
                    raise RuntimeError(error_message)

    def print_images(self, images: list[Image], margin_px: int = 0):
        self.update_status()
        pages_left = len(images)
        for image in images:
            image = prepare_image(image, self.media_width)
            if (image.width + margin_px) < MINIMUM_TAPE_POINTS:
                warnings.warn("Image (%i) + cut margin (%i) is smaller than minimum tape width (%i) ... "
                              "cutting length will be extended" % (image.width, margin_px, MINIMUM_TAPE_POINTS))
            data = raster_image(image, self.media_width)
            pages_left -= 1
            self.print_data(data, margin_px, pages_left == 0)


if __name__ == '__main__':
    printer = BrotherPt()
    print("Media width: %dmm" % printer.media_width)
    print("Media type : %s" % printer.media_type.name)
    print("Tape color : %s" % printer.tape_color.name)
    print("Text color : %s" % printer.text_color.name)
    print()
    if len(sys.argv) != 2:
        print("%s <imagename>" % sys.argv[0], file=sys.stderr)
        sys.exit(1)
    image = Image.open(sys.argv[1])

    printer.print_image(image)
