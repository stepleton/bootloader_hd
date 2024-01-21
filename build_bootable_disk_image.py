#!/usr/bin/python3
"""Build a bootable Apple Lisa hard disk image.

Forfeited into the public domain with NO WARRANTY. Read LICENSE for details.

Supports 5MB and 10MB disk images, in DC42 and raw formats. Includes a built-in
copy of the "bootloader_hd" bootloader, making this program all you need to
make a bootable Lisa disk image. Run this program with the `--help` option for
usage documentation, and view the <README.md> file for background information
and definitions of technical terms.

NOTE: This program is not capable of adding a bootloader to an existing disk
image file! (And attempting to use it that way will likely cause this program
to overwrite and destroy the file, too.) Instead, all it can do is take a file
containing raw 68000 machine code (which expects to be loaded directly into the
Lisa's memory starting at location $800, then executed from that address), and
place it along with the bootloader at the beginning of a newly-created,
otherwise empty (zero-padded) disk image.

This program can output disk images in four formats:

   - "raw" -- a concatenation of all the blocks in hard drive as if they were
     read directly from the drive in sequential order, suitable for use with
     the IDLE emulator and the Cameo/Aphid ProFile emulator
     (https://github.com/stepleton/cameo/tree/master/aphid),

   - "dc42" -- a DC42 disk image file in the format used by the LisaEm emulator,

   - "blu" -- a disk image file compatible with the Basic Lisa Utility from
     http://sigmasevensystems.com/BLU.html, and

   - "usbwidex" -- an image file identical to the storage format for the IDEFile
     ProFile emulator (http://john.ccac.rwth-aachen.de:8000/patrick/idefile.htm)
     and suitable for use with the UsbWidEx hard drive diagnostic tool
     (http://john.ccac.rwth-aachen.de:8000/patrick/UsbWidEx.htm) with image
     options "Y, N, N".
     
The output format is controlled by `--format`.

For each format, the `--device` flag specifies the target (or emulated) disk
device, mainly affecting the size of the disk image (which, notwithstanding,
can be customised with the `--blocks` flag). For `--format=blu`, the `--device`
flag also changes aspects of internal data ordering to ensure that BLU writes
data to disks in the manner that the "bootloader_hd" bootloader expects.

Short lines of text in the `--tags_file` are displayed on the Lisa's screen as
corresponding blocks are loaded from the drive. (that is, the first line in
the file is shown as the first block is loaded; the second for the second block,
and so on. No text is shown for the last block loaded from the disk; the text
from the prior block remains on view. Only the first 18 characters of each line
are displayed, and each of these must be a numeral, an uppercase Latin letter,
or one of "./-?".

This program originated at https://github.com/stepleton/bootloader_hd, and may
have been modified if obtained elsewhere.

Advice from Ray Arachelian is gratefully acknowledged, along with help from the
following references:
   - http://sigmasevensystems.com/blumanual.html
   - https://wiki.68kmla.org/index.php?title=DiskCopy_4.2_format_specification
   - https://github.com/rayarachelian/lisaem/blob/master/src/tools/src/raw-to-dc42.c
   - https://github.com/rayarachelian/lisaem/blob/master/src/tools/src/blu-to-dc42.c
   - http://john.ccac.rwth-aachen.de:8000/patrick/idefile.htm
   - http://john.ccac.rwth-aachen.de:8000/patrick/UsbWidEx.htm

This program and all bootloader programs stored inside it are released into the
public domain without any warranty. For details, refer to the LICENSE file
distributed with this program, or, if it's missing, to:
  - https://github.com/stepleton/bootloader_hd/blob/master/LICENSE
For further information, visit http://unlicense.org.


Revision history
----------------

This section records the development of this file as part of the
`bootloader_hd` project at <http://github.com/stepleton/bootloader_hd>.

30 March 2020: Initial release.
(Tom Stepleton, stepleton@gmail.com, London)

6 February 2021: Support for truncated image files (--clip). (Tom Stepleton)

21 January 2024: Improved organisation to support use of this module in other
programs. (Tom Stepleton)
"""

import argparse
import base64
import math
import struct
import sys
import textwrap
import warnings

from typing import IO, Iterator, List, Optional, Sequence, Tuple, Union


def _define_flags():
  """Defines an `ArgumentParser` for command-line flags used by this program."""
  flags = argparse.ArgumentParser(
      description='Build a bootable Apple Lisa hard disk image')

  flags.add_argument('program',
                     help=('Raw 68000 machine code program binary to load+run '
                           '(starting address $800)'),
                     type=argparse.FileType('rb'))

  flags.add_argument('-f', '--format',
                     help=('Target format for hard drive image file: dc42 is a '
                           'Disk Copy 4.2 file suitable for use with LisaEm; '
                           'blu is a disk image suitable for use with the '
                           'Basic Lisa Utility, raw is a sequential collection '
                           'of block data suitable for use with the '
                           'Cameo/Aphid hard drive emulator and with IDLE, and '
                           'usbwidex is a disk image suitable for use with the '
                           'UsbWidEx hard drive diagnostic tool.'),
                     choices=IMAGE_FORMATS,
                     default='dc42')

  flags.add_argument('-d', '--device',
                     help=('Create an image for a particular device; note that '
                           'this flag primarily determines the default number '
                           'of blocks on the device and otherwise only affects '
                           'the formatting of "blu" disk images'),
                     choices=DEVICES,
                     default='profile')

  flags.add_argument('-k', '--blocks',
                     help=('Number of blocks in the disk image: specify 0 to '
                           'use the default for the device specified by the '
                           '--device flag or the minimal "clipped" length '
                           'calculated when --clip is set, and beware that '
                           'nonstandard sizes may not work with most '
                           'emulators or utility programs'),
                     type=int)

  flags.add_argument('-o', '--output',
                     help=('Where to write the resulting disk image; if '
                           'unspecified, the image is written to standard out'),
                     type=argparse.FileType('xb'))

  clipflag = flags.add_mutually_exclusive_group(required=False)
  clipflag.add_argument('-c', '--clip', dest='clip', action='store_true',
                        help=('Clip disk images to only the blocks required to '
                              'store the bootloader and the program; may not '
                              'be sensible if your program intends to write '
                              'to the drive image at any point; images may not '
                              'work with most emulators or utility programs'))
  clipflag.add_argument('--noclip', dest='clip', action='store_false',
                        help=argparse.SUPPRESS)
  flags.set_defaults(clip=False)

  flags.add_argument('-t', '--tags_file',
                     help=('Text file listing per-block loading display tags, '
                           'one per line, maximum length 18 characters, and '
                           'using only the characters in "0-9A-Z ./-?"'),
                     type=argparse.FileType('r'))

  flags.add_argument('-b', '--bootloader',
                     help=('"bootloader_hd" bootloader for loading the '
                           'program as a binary file containing MC68000 '
                           'machine code; if unspecified, a built-in copy of '
                           'the bootloader will be used'),
                     type=argparse.FileType('rb'))

  return flags


# The number of 532-byte blocks in complete drive images of:
_DEFAULT_NUM_BLOCKS = {'profile': 0x2600,     # A 5 "megabyte" ProFile drive.
                       'profile-10': 0x4c00,  # A 10 "megabyte" ProFile.
                       'widget': 0x4c00}      # A 10 "megabyte" Widget drive.

# Names of the disk image formats that this code can generate. For more
# information about the formats these names refer to, see the module docstring
# and the documentation for the --format flag.
IMAGE_FORMATS = ('dc42', 'blu', 'raw', 'usbwidex')
# Names of Apple parallel hard drive devices that disk images can pretend to
# be imaged from. For more information about how and when these names are used,
# see the documentation for the --device flag.
DEVICES = tuple(_DEFAULT_NUM_BLOCKS)

# This 18 byte sequence makes up all but the first two (checksum) bytes of the
# last block that the bootloader should load from the disk. It is not shown to
# the user.
TAG_FOR_LAST_BLOCK = b' bit.ly/3arucNJ  \x00'

# This built-in bootloader binary is the version released on 30 March 2020.
# It's quite a bit larger than the "Stepleton" floppy disk bootloader, but
# there's an entire ProFile I/O library in there...
_BUILT_IN_BOOTLOADER = textwrap.dedent("""\
    WW8hIKqqIEknbSBib290YWJsZSEQOAGzYRphAACcckDliTQ8CgNB+gHsYQABKmcAAvBOQDI8APxI
    QTI83YEiQZL8BIB0BFcAaxxRAGoYdBAyPOABBEFAAFYAa/hTAGcEBkEIACJBQfoAKiDB0kIgwUXp
    AGAgykXpABAgyiDJRekAGCDKRekAeCDKRekACCDKTnU8LS0tLVpvbmUgZm9yIFZJQSBhZGRyZXNz
    ZXMtLS0tPgAAU1RBVEjnAPxB+v/UTNA/AAAQAKAAEQCgAhIAewASAGsavAAAABQAGAIUAPsCEwD8
    ABMAHAgUAABM3z8ATnVCEQISAO8WvAAASEAwPP//CBIAAWcKTnFOcVHI//RgJEhAsBRW0VfAAkAA
    VQISAOcWvAD/GIAAEgAQSEBCQOSIYRJmBAARAAEWvAAAABIAGEoRTnVSgAgSAAFmBFOAZvZOdWCc
    SOcAfEP6/0ZM2TwAQOcAfAcAQhFwCEhAYdZmBlQRYAAAgHABYdhrAAB4Zw5wCO2IYb5nbHABYcZm
    ZgISAPcWvAD/cAMageGZUcj/+uFaGoLhWhqCFrwAAAASAAgQAVQAYZxmPDA8AhNKAWceAhIA9xa8
    AP8amFHI//wWvAAAABIACHAGYQD/FmYWSfr+0hjVGNUY1RjVSgFmBhDVUcj//EbfShFM3z4ATnUA
    AAAAAAAAAAAAAAAAAAAAAAAAACBiaXQubHkvM2FydWNOSiAgAAAAMHwIANKHYQD/JmY2YTpnHkIo
    ABJI52GAR+gAAnoNfBh4GE65AP4AiEzfAYZg1kH6/dxD+v5cRfr+9kf6/k5O+AgAR/oAWGBIkPwC
    FCJITNl8AHB/INlRyP/8SNB8AEjnYYCQ/AIAMDwBAEJBTrkA/gC8TN8BhmUUQ+gAAkX6/24QGrAZ
    ZgRKAGb2TnVH+gA7IAHgiJXKTrkA/gCEUkVBRCBFUlJPUi4uLiBTRUNUT1IgTlVNIFNIT1dOIElO
    IEVSUk9SIENPREUAQkFEIENIRUNLU1VNLi4uIFNFQ1RPUiBOVU0gU0hPV04gSU4gRVJST1IgQ09E
    RQAwPALsIHgCqND8gACQwEP6/QRTQBDZUcj//C4BkPwA+E7Q""")


def main(FLAGS):
  # No tags_file listed? We supply a boring stand-in.
  tags_file = FLAGS.tags_file or DefaultTags()
  # No output file listed? Use stdout in binary mode.
  output_file = FLAGS.output or sys.stdout.buffer

  # If a file containing a bootloader is specified, load it; otherwise specify
  # None to use the default bootloader.
  if FLAGS.bootloader:
    bootloader, _ = _read_binary_data(FLAGS.bootloader, 1064, 'bootloader')
  else:
    bootloader = None

  # Load program; if smaller than the disk data capacity minus 1024 (for the
  # blocks already used by the bootloader), pad it out with zeros, unless
  # clipping is desired.
  program, program_size = _read_binary_data(
      FLAGS.program, 0x200 * num_blocks - 0x400, 'program', FLAGS.clip)
  program_blocks = math.ceil(program_size / 0x200)

  # If clipping is specified without the number of blocks specified, then all
  # the blocks we need are the two for the program plus two more for the
  # bootloader. Otherwise we go with the value in the --blocks flag, which can
  # be zero to defer to the number of blocks entailed by the --device flag.
  num_blocks = ((program_blocks + 2)
                if FLAGS.clip and not FLAGS.blocks else FLAGS.blocks)

  # Make the bootloader and tag data for the drive.
  tags, data = make_tags_and_data(
      device=FLAGS.device, program=program,
      bootloader=bootloader, display_tags=tags_file,
      num_blocks=num_blocks)

  # Compile into a drive image.
  image = make_drive_image(tags, data, FLAGS.format, FLAGS.device)

  # Write image to output
  output_file.write(image)


# returns: data data, tags data
def make_tags_and_data(
    device: str,
    program: bytes,
    bootloader: Optional[bytes] = None,
    display_tags: Optional[Iterator[str]] = None,
    num_blocks: Optional[int] = None,
) -> Tuple[List[bytes], List[bytes]]:
  """Create block data and block tags for a bootable hard drive image.

  Args:
    device: Device type string (valid values are listed in the DEVICES tuple
        and documented at the --device flag definition).
    program: Raw 68000 machine code program binary to load and run (starting
        address $800).
    bootloader: Raw 68000 machine code bootloader binary; if unspecified or
        None, will use bootloader data built into the module.
    display_tags: An iterator over up to 18-byte strings to display while
        loading blocks of program data; must use only characters in
        "0-9A-Z ./-?". If unspecified or None, will use "default" display tags.
    num_blocks: Generate block data and block tags for exactly this many
        blocks; if unspecified or None, will create these for as many blocks
        are present on the device named by the `device` argument.

  Returns:
    [1] A list of 20-byte binary tags, one for each block in the drive image.
    [2] A list of 512-byte binary data blocks, one for each block in the image.
  """
  # Early argument checking.
  if device not in DEVICES: raise ValueError(
      f'Invalid drive device type "{device}"; valid drive device types are ' +
      ', '.join(f'"{d}"' for d in DEVICES))

  # Fill in default values where unspecified, plus a bit more arg checking.
  bootloader = (bootloader or
                base64.decodebytes(bytes(_BUILT_IN_BOOTLOADER, 'ascii')))
  display_tags = display_tags or DefaultTags()
  num_blocks = num_blocks or _DEFAULT_NUM_BLOCKS[device]
  if num_blocks < 3: raise ValueError(
    f'A disk image of {num_blocks} blocks has no room for any program data')

  # Pad bootloader to two full blocks; complain if it's bigger than that.
  if len(bootloader) > 1064: raise ValueError(
      f'Bootloader was {len(bootloader)} bytes long, but can be no larger '
      'than 1064 bytes (two 532-byte blocks)')
  bootloader += b'\x00' * (1064 - len(bootloader))

  # Chop bootloader into per-block data and tags for the first two blocks.
  bootloader_data = [bootloader[20:532], bootloader[552:]]
  bootloader_tags = [bootloader[:20], bootloader[532:552]]

  # Pad program data out to 512 * the number of blocks in the image less two
  # (to accommodate the bootloader). (It's 512 because that's the number of
  # data bytes in a block; the 20 extra bytes are the tag bytes.)
  program_size = len(program)  # Pre-padding size of the original program
  data_space = 0x200 * (num_blocks - 2)  # Total non-tag bytes in the image
  if data_space < program_size: raise ValueError(
      f'Program data of length {program_size} bytes exceeds the {data_space} '
      f'non-bootloader bytes available in a {num_blocks}-block {device} image')
  program += b'\x00' * (data_space - program_size)

  # How many blocks does the program occupy prior to padding?
  program_blocks = math.ceil(program_size / 0x200)

  # Chop padded program into per-block data.
  program_data = [program[i:i+0x200] for i in range(0, len(program), 0x200)]

  # Compute the per-block checksums that the bootloader uses to verify the
  # program's integrity, then assemble tags for the program data.
  program_checksums = [checksum(d) for d in program_data[:program_blocks]]
  program_tags = [c + _read_next_tag(display_tags)
                  for c in program_checksums[:-1]]
  program_tags.append(program_checksums[-1] + TAG_FOR_LAST_BLOCK)
  program_tags.extend([b'\x00' * 20] * (num_blocks - program_blocks - 2))

  # Combine tags and data for all blocks, and return
  tags = bootloader_tags + program_tags
  data = bootloader_data + program_data
  return tags, data


def make_drive_image(
    tags: Sequence[bytes],
    data: Sequence[bytes],
    image_format: str,
    device: str,
) -> bytes:
  """Compile per-block tags and data into one of several disk image formats.

  Compiles `tags` and `data` into disk image data representing data on a
  specified disk device. For more information about the image formats made by
  this function, see the module docstring and documentation at the definition
  of the --format flag; likewise, for information about device types, refer to
  the --device flag.

  Args:
    tags: 20-byte block tags to place in the disk image, in linear order.
    data: 512-byte block data records to place in the disk image, in linear
        order.
    image_format: Image format string (valid values are listed in the
        IMAGE_FORMATS tuple and documented at the --format flag definition
        and in the module docstring).
    device: Device type string (valid values are listed in the DEVICES tuple
        and documented at the --device flag definition).

  Returns: Binary data of a LisaEm-compatible .dc42 disk image, ready to be
      written to a file.
  """
  if image_format == 'dc42':
    return _make_apple_parallel_drive_image_dc42(tags, data, device)
  elif image_format == 'blu':
    return _make_apple_parallel_drive_image_blu(tags, data, device)
  elif image_format == 'raw':
    return b''.join(sum(zip(tags, data), ()))
  elif image_format == 'usbwidex':  # It's "raw" w/sectors padded to 1024 bytes.
    return b''.join([t + d + b'\x00' * 0x1ec for t, d in zip(tags, data)])
  else:
    raise ValueError(f'Unrecognised disk image format {format}')


def _read_binary_data(
    fp: IO,
    size: int,
    name: str,
    clip: bool = False,
) -> Tuple[bytes, int]:
  """Read zero-padded binary data from a file.

  Attempts to read `size+1` bytes from filehandle `fp`. If 0 or more than `size`
  bytes are read, raises an IOError. Data of any other size is returned to the
  caller, followed by enough zero padding to yield `size` bytes exactly (if
  `clip` is False) or to yield the nearest larger multiple of 0x200 (if `clip`
  is True).

  Args:
    fp: file object to read from.
    size: number of bytes to read from `fp`.
    name: name for data being loaded (used for exception messages).
    clip: whether to pad binary data with 0s to the nearest larger multiple of
        0x200 (if True) or to `size` (if False).

  Returns: a 2-tuple whose members are the data loaded from `fp` (zero-padded)
      and the original size of the data in bytes prior to zero-padding.

  Raises:
    IOError: if the file is empty or contains more than size bytes.
  """
  # Read data.
  data = fp.read(size + 1)  # type: bytes
  if len(data) == 0:
    raise IOError(f'failed to read any {name} data')
  if len(data) > size:
    raise IOError(f'{name} data file was larger than {size} bytes')

  # Zero-pad and return.
  if clip:
    return data + (b'\x00' * (0x200 + ~((len(data)-1) & 0x1ff))), len(data)
  else:
    return data + (b'\x00' * (size - len(data))), len(data)


def checksum(block: bytes) -> bytes:
  """Compute add-and-shift-left-1 16-bit big-endian checksum."""
  checksum = 0
  for i in range(0, len(block), 2):
    w = struct.unpack_from('>H', block, i)[0]  # Collect next word
    checksum = (checksum + w) & 0xffff         # Add word to checksum
    checksum = ((checksum << 1) + (checksum >> 15)) & 0xffff  # Rotate left by 1
  return struct.pack('>H', (0x10000 - checksum) & 0xffff)  # Complement


def _read_next_tag(fp: Iterator[str]) -> bytes:
  """Read the next tag from the tag file.

  Attempts to read the next item from the iterator (usually a text file) `fp`
  for use as the printable final 18 bytes of a block tag.  bootloader_hd
  prints the last 18 bytes of all but the final block's tag to the screen,
  making these tags useful progress indicators. Tags can be up to eighteen
  bytes long and may only contain the characters A..Z, 0..9, and "./-?" (quotes
  not included), which are all that's defined in the ROM. Any tag with fewer
  than eighteen characters will be padded with spaces.

  Args:
    fp: iterator to read tags from.

  Returns: 18-byte string for use as the printable part of a block tag.

  Raises:
    IOError: if end of file is encountered.
    RuntimeError: if a tag uses characters not found in the Lisa Boot ROM.
  """
  # Read "raw" line and clip away CR/CRLF/LF.
  try:
    tag = next(fp)
  except StopIteration:
    raise IOError('ran out of tags in the tag file.')
  tag = tag.rstrip('\r\n')

  # Scan line for chars not in the ROM.
  if any(c not in '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ ./-?' for c in tag):
    raise RuntimeError('tag {} has chars not found in the ROM'.format(tag))

  # Warn if the tag is too long and truncate to 20 bytes.
  if len(tag) > 18:
    warnings.warn('tag {} will be clipped to 18 bytes'.format(tag), UserWarning)
    tag = tag[:18]

  # Space-pad, convert to bytes, and return.
  return bytes(tag + (' ' * (18 - len(tag))), 'ascii')


class DefaultTags:
  """Boring "tags file" stand-in object.

  Tags taken from this iterator will display boring messages to the user during
  loading, e.g.
     READ 0.5K...
     READ 1.0K...
     READ 1.5K...
  and so on.
  """

  def __init__(self):
    self._blocks_read = 0

  def __iter__(self) -> Iterator[str]:
    return self

  def __next__(self) -> str:
    self._blocks_read += 1
    return 'READ {}K...\n'.format(0.5 * self._blocks_read)


def _make_apple_parallel_drive_image_dc42(
    tags: Sequence[bytes],
    data: Sequence[bytes],
    device: str,
) -> bytes:
  """Compile per-block tags and data into a LisaEm-compatible .dc42 disk image.

  Compiles `tags` and `data` into a .dc42 disk image file compatible with the
  LisaEm emulator. For now, this means:
     - unique "magic" encoding and format bytes of $5D and $93 respectively
     - a permutation of each non-overlapping contiguous set of 32 blocks that
       "cancels out" LisaEm's de-interleaving of LisaOS's 5:1 interleaving
       scheme for ProFiles.

  This interleaving scheme means that no matter the length of tags/data, the
  final size of the image will be padded out to have the next largest multiple
  of 32 blocks. Any padding blocks (which are "mixed in" with real blocks during
  the permutation process) will be filled in with zeros.

  Reference materials for this implementation:
     1. http://sigmasevensystems.com/blumanual.html
     2. https://wiki.68kmla.org/index.php?title=DiskCopy_4.2_format_specification
     3. https://github.com/rayarachelian/lisaem/blob/master/src/tools/src/raw-to-dc42.c

  Args:
    tags: 20-byte block tags to place in the disk image, in linear order.
    data: 512-byte block data records to place in the disk image, in linear
        order.
    device: Device type string (valid values are listed in the DEVICES tuple
        and documented at the --device flag definition); not used by this
        function for now.

  Returns: Binary data of a LisaEm-compatible .dc42 disk image, ready to be
      written to a file.
  """
  DC42_NAME = struct.pack('64p', b'-not a Macintosh disk-')
  DC42_ENCODING = b'\x5d'   # LisaEm-custom DC42 encoding byte.
  DC42_FORMAT = b'\x93'     # LisaEm-custom DC42 format byte.
  DC42_MAGIC = b'\x01\x00'  # DC42 "magic number" string.

  # LisaEm permutes the ordering of logical blocks in hard drive image .dc42
  # files: in every successive non-overlapping contiguous set of 32 blocks, the
  # n'th block will be moved to position LISAEM_DEINTERLEAVE[n]. This mapping
  # linearises the interleaving scheme that LisaOS uses on ProFiles. The local
  # function `permute` immediately below applies this permutation.
  LISAEM_DEINTERLEAVE = (0, 13, 10, 7, 4,
                         1, 14, 11, 8, 5,
                         2, 15, 12, 9, 6,
                         3,
                         16, 29, 26, 23, 20,
                         17, 30, 27, 24, 21,
                         18, 31, 28, 25, 22,
                         19)

  def permute(original: Sequence[bytes]) -> List[bytes]:
    """Permute items in `original` by the LISAEM_DEINTERLEAVE scheme."""
    permuted = []
    for i in range(0, len(original), 32):  # Works in 32-block chunks.
      sub_original = original[i:i+32]
      sub_permuted = [b'\x00' * len(sub_original[0])] * 32
      for j, item in enumerate(sub_original):
        sub_permuted[LISAEM_DEINTERLEAVE[j]] = item
      permuted.extend(sub_permuted)
    return permuted

  ### Actual work begins here. ###

  del device  # Unused, for now.

  # Now apply the permutation and concatenate data and tags.
  data_cat = b''.join(permute(data))
  tags_cat = b''.join(permute(tags))

  # We can compute the checksums and lengths for the data and tags.
  data_length = struct.pack('>I', len(data_cat))
  tags_length = struct.pack('>I', len(tags_cat))
  data_checksum = _dc42_checksum(data_cat)
  tags_checksum = _dc42_checksum(tags_cat[12:])  # see cited reference #2

  # Assemble the .dc42 image.
  return b''.join([DC42_NAME,
                   data_length, tags_length,
                   data_checksum, tags_checksum,
                   DC42_ENCODING, DC42_FORMAT, DC42_MAGIC,
                   data_cat, tags_cat])


def _dc42_checksum(data: bytes) -> bytes:
  """Compute the checksum DC42 uses to verify data and tag integrity.

  Args:
    data: data to compute a checksum for.

  Returns: a 32-bit (big endian) checksum.
  """

  def addl_rorl(uint: int, csum: int) -> int:
    """Add `uint` to `csum`; 32-bit truncate; 32-bit rotate right one bit."""
    csum += uint        # add uint
    csum &= 0xffffffff  # truncate
    rbit = csum & 0x1   # rotate part 1 (save low-order bit)
    csum >>= 1          # rotate part 2 (shift right)
    csum += rbit << 31  # rotate part 3 (prepend old low-order bit)
    return csum

  # Loop over all two-byte words in the data and include them in the checksum.
  checksum = 0
  for word_bytes in [data[i:i+2] for i in range(0, len(data), 2)]:
    word = struct.unpack('>H', word_bytes)[0]  # big endian word bytes to native
    checksum = addl_rorl(word, checksum)       # add to checksum

  # return result as a big-endian 32-bit word.
  return struct.pack('>I', checksum)


def _make_apple_parallel_drive_image_blu(
    tags: Sequence[bytes],
    data: Sequence[bytes],
    device: str,
) -> bytes:
  """Compile per-block tags and data into a BLU-compatible disk image.

  Compiles `tags` and `data` into a disk image file compatible with the Basic
  Lisa Utility. For now, this means:
     - for Widget images, a reordering of data and tags that "cancels out" BLU's
       Widget-specific placement of tags after images.
     - for ProFile images, a permutation of each non-overlapping contiguous set
       of 32 blocks that "cancels out" BLU's de-interleaving of LisaOS's 5:1
       interleaving scheme for ProFiles.

  This interleaving scheme means that no matter the length of tags/data, the
  final size of any ProFile image will be padded out to have the next largest
  multiple of 32 blocks. Any padding blocks (which are "mixed in" with real
  blocks during the permutation process) will be filled in with zeros.

  Reference materials for this implementation:
     1. http://sigmasevensystems.com/blumanual.html
     2. https://github.com/rayarachelian/lisaem/blob/master/src/tools/src/blu-to-dc42.c

  Args:
    tags: 20-byte block tags to place in the disk image, in linear order.
    data: 512-byte block data records to place in the disk image, in linear
        order.
    device: Device type string (valid values are listed in the DEVICES tuple
        and documented at the --device flag definition).

  Returns: Binary data of a BLU-compatible disk image, ready to be written to a
      file.
  """
  ID_DATA = {
      'profile': (
          b'PROFILE      '  # Device name. This indicates a 5MB ProFile.
          b'\x00\x00\x00'   # Device number. Also means "5MB ProFile".
          b'\x03\x98'       # Firmware revision $0398. (Latest sold?)
          b'\x00\x26\x00'   # Blocks available. 9,728 blocks.
          b'\x02\x14'       # Block size. 532 bytes.
          b'\x20'           # Spare blocks on device. 32 blocks.
          b'\x00'           # Spare blocks allocated. 0 blocks.
          b'\x00'           # Bad blocks allocated. 0 blocks.
          b'\xff\xff\xff'   # End of the list of (no) spare blocks.
          b'\xff\xff\xff'   # End of the list of (no) bad blocks.
      ) + b'\x00' * (0x200 - 32),  # Pad to $200 bytes.
      'profile-10': (
          b'PROFILE 10M  '  # Device name. This indicates a 10MB ProFile.
          b'\x00\x00\x01'   # Device number. Also means "10MB ProFile".
          b'\x04\x04'       # Firmware revision $0404.
          b'\x00\x4C\x00'   # Blocks available. 19,456 blocks.
          b'\x02\x14'       # Block size. 532 bytes.
          b'\x20'           # Spare blocks on device. 32 blocks.
          b'\x00'           # Spare blocks allocated. 0 blocks.
          b'\x00'           # Bad blocks allocated. 0 blocks.
          b'\xff\xff\xff'   # End of the list of (no) spare blocks.
          b'\xff\xff\xff'   # End of the list of (no) bad blocks.
      ) + b'\x00' * (0x200 - 32),  # Pad to $200 bytes.
      'widget': (
          b'Widget-10    '  # NameString
          b'\x00\x01\x00'   # Device.Widget + Widget.Size + Widget.Type
          b'\x1a\x45'       # Firmware_Revision
          b'\x00\x4c\x00'   # Capacity (19,456 blocks, 10 MB)
          b'\x02\x14'       # Bytes_Per_Block (532)
          b'\x02\x02'       # Number_Of_Cylinders (514)
          b'\x02'           # Number_Of_Heads (2)
          b'\x13'           # Number_Of_Sectors (19)
          b'\x00\x00\x4c'   # Number_Of_Possible_Spare_Locations (76)
          b'\x00\x00\x00'   # Number_Of_Spared_Blocks (None!)
          b'\x00\x00\x00'   # Number_Of_Bad_Blocks (None!)
      ) + b'\x00' * (0x200 - 36),  # Pad to $200 bytes.
  }
  # This is the tag that BLU gives to disk images, although cited reference #1
  # implies that it can be any string that describes "the source of the image".
  # We'll just reuse BLU's calling card verbatim: other utilities may treat it
  # as a magic number, and we have no desire for fame ourselves.
  ID_TAG = b'Lisa HD Img BLUV0.90'

  # BLU permutes the ordering of logical blocks in ProFile hard drive images:
  # in every successive non-overlapping sequence of 32 blocks, the n'th block
  # will be moved to position BLU_PROFILE_DEINTERLEAVE[n]. This mapping
  # linearises the interleaving scheme that LisaOS uses on ProFiles. The local
  # function `permute` immediately below applies this permutation.
  BLU_PROFILE_DEINTERLEAVE = (0, 13, 10, 7, 4,
                              1, 14, 11, 8, 5,
                              2, 15, 12, 9, 6,
                              3,
                              16, 29, 26, 23, 20,
                              17, 30, 27, 24, 21,
                              18, 31, 28, 25, 22,
                              19)

  def permute(original: Sequence[bytes]) -> List[bytes]:
    """Permute items in `original` by the BLU_PROFILE_DEINTERLEAVE scheme."""
    permuted = []
    for i in range(0, len(original), 32):  # Works in 32-block chunks.
      sub_original = original[i:i+32]
      sub_permuted = [b'\x00' * len(sub_original[0])] * 32
      for j, item in enumerate(sub_original):
        sub_permuted[BLU_PROFILE_DEINTERLEAVE[j]] = item
      permuted.extend(sub_permuted)
    return permuted

  ### Actual work begins here. ###

  # Construct identification block. This isn't part of the disk: it's a
  # block-sized header that precedes the disk data.
  try:
    blu_blocks = [ID_DATA[device] + ID_TAG]
  except KeyError:
    raise ValueError(
        f"creating blu images with --format={device} isn't supported yet")

  # Assemble the remaining blocks, which in a BLU image are always arranged with
  # the data preceding the tag. Now, when writing an image to a disk on a Lisa,
  # BLU knows that in a ProFile block the tags always come first, while in a
  # Widget block, the LisaOS stores tags *after* the data, So, that's where it
  # puts the tags when it writes to a Widget. Our bootloader doesn't give
  # Widgets special treatment, so we have to reorder the data when making Widget
  # BLU images so that BLU winds up writing our tags in the ProFile location.
  if FLAGS.format.startswith('widget'):  # Maybe a Widget-20 turns up someday...
    blu_blocks.extend(t + d for d, t in zip(data, tags))
  else:
    blu_blocks.extend(d + t for d, t in zip(data, tags))

  # Apply the permutation for ProFile disk images.
  if FLAGS.format.startswith('profile'):
    blu_blocks = [blu_blocks[0]] + permute(blu_blocks[1:])

  # Concatenate blocks for the final image.
  return b''.join(blu_blocks)


if __name__ == '__main__':
  flags = _define_flags()
  FLAGS = flags.parse_args()
  main(FLAGS)
