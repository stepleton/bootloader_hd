`bootloader_hd` -- Apple parallel port hard drive bootloader for Lisa
=====================================================================

This repository is home to a bootloader for executable code on Apple parallel
port hard drives (ProFile, Widget) and compatible emulators (IDEFile,
X/ProFile, Cameo/Aphid, etc.). The bootloader occupies the first two blocks of
a hard drive and loads a program from blocks immediately following. It can run
from a hard drive connected to any ordinary Lisa parallel port: fixed/internal
or on an expansion card.


Documentation
-------------

Because people might choose to package the bootloader into their own software
projects, nearly all important documentation---including references,
acknowledgements, and release history---appears within the source code files
themselves.


Files
-----

- [`bootloader_hd.x68`](bootloader_hd.x68)
  Source code for the hard drive bootloader. Refer to its header comment for
  extensive documentation.

- [`build_bootable_disk_image.py`](build_bootable_disk_image.py)
  A standalone Python program for generating a bootable Apple parallel port
  hard drive disk image that loads and executes a program you supply.


Nobody owns `bootloader_hd`
---------------------------

The hard drive bootloader and any supporting programs, software libraries, and
documentation distributed alongside it are released into the public domain
without any warranty. See the [LICENSE](LICENSE) file for details.
