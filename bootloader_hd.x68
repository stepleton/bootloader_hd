* Apple parallel port hard drive bootloader for Lisa
* ==================================================
*
* Forfeited into the public domain with NO WARRANTY. Read LICENSE for details.
*
* This is a bootloader for executable code on Apple parallel port hard drives
* (ProFile, Widget) and compatible emulators (IDEFile, X/ProFile, Cameo/Aphid,
* etc.). It occupies the first two blocks of a hard drive and loads a program
* from blocks immediately following.
*
* The bootloader can run from a hard drive connected to any ordinary Lisa
* parallel port: fixed/internal or on an expansion card.
*
*
* Operational details
* -------------------
*
* The bootloader loads programs into RAM starting at address $800. The program
* data occupies bytes $14-$213 of each block, with bytes $0-$13 holding a 16-bit
* data checksum and an 18-character message to show the user after the block is
* loaded. A special message string marks the final block to load and is not
* shown. Once loaded, the bootloader jumps to $800 to execute the program.
*
* The bootloader incorporates a small library for blocking reads and writes to
* Apple parallel port hard drives: the `lisa_profile_io.x68` component from
* https://github.com/stepleton/lisa_io . The library remains memory resident
* after loading completes and can be used by the loaded program if desired.
* Prior to jumping to $800, the bootloader leaves pointers to key library
* procedures and data in address registers A0-A3:
*
*    A0: `ProFileIoSetup` -- to reset the library or change the target device
*    A1: `ProFileIoInit` -- to initialise VIAs for the target device
*    A2: `ProFileIo` -- read from or write to the target device
*    A3: `zProFileErrCode` -- error code from these procedures
*
* For more information refer to the `lisa_io` documentation. Programs need not
* call `ProFileIoSetup` or `ProFileIoInit` if they will only access the device
* that the program was loaded from.
*
* The bootloader leaves ROM-reserved memory locations $000000-$0007FF untouched
* and does not alter the MMU setup, allowing the loaded program to make use of
* externally-callable routines and other resources in the Lisa's boot ROM.
*
*
* Errors
* ------
*
* The bootloader can generate three types of errors that "crash" back into the
* ROM monitor:
*
*    - A sudden Error 47 means that the bootloader has failed to load its
*      second stage from disk block $000001.
*
*    - A block read error yields a message starting with "READ ERROR" and the
*      decimal block number of the offending block.
*
*    - A block checksum mismatch yields a message starting with "BAD CHECKSUM"
*      and the decimal block number of the offending block.
*
* Other errors or strange behaviour may indicate problems with your Lisa or an
* attempt to load a program larger than available RAM.
*
*
* Creating a bootable disk image
* ------------------------------
*
* Many users of the bootloader will want to create bootable disks using the
* included `build_bootable_disk_image.py` script. The script is standalone:
* it contains a binary copy of the bootloader. Refer to the documentation
* and flags within the script for usage details.
*
* The script creates a new ProFile disk image containing the bootloader and
* a program that you supply. It automates the following procedure:
*
* 1. Fill the first block of the disk ($000000) with the first 532 bytes of the
*    bootloader binary.
*
* 2. Place the rest of the bootloader binary at the beginning of the second
*    disk block ($000001); leftover space can be filled as you wish.
*
* 3. Pad your program out to the nearest multiple of 512 bytes with any data.
*
* 4. Divide the result into 512-byte chunks. For each chunk, assemble a 20-byte
*    "tag" comprising:
*
*    - first, a 16-bit checksum computed as the two's complement of the result
*      of adding each byte to a $0000-initialised 16-bit big-endian quantity
*      and rotating the result of each addition one bit to left (see the
*      `_checksum` function in `build_bootable_disk_image`).
*
*    - next, an 18-byte string to display on the screen as the bootloader loads
*      the chunk into memory. The string may only contain the ASCII characters
*      A-Z, 0-9, and -./? (along with a blank, which corresponds to ASCII $20,
*      or space). (Note: no lowercase letters.) If a NUL ($00) character is
*      present in the string, only characters preceding the NUL will display,
*      and text from chunks loaded earlier that is not overwritten will remain
*      on the screen. (Hint: pad short tags with $20 characters instead.)
*
* 5. Replace the display string for the final block with the first 18 bytes of
*    the string defined at location `BlockOne` below (i.e. up through the first
*    $00 byte).
*
* 6. Prepend the tags to the chunks, and copy the results onto successive disk
*    blocks, starting with $000002.
*
*
* Internals
* ---------
*
* **Background:** When the Lisa boots, the 68000's 24-bit address space can be
* divided as follows (assuming a Lisa with 1 MB of RAM):
*
*    - $000000 - $0007FF: System configuration and status information in RAM,
*      and RAM space reserved for use by the boot ROM.
*    - $000800 - $0F7FFF: *Free RAM.*
*    - $0F8000 - $0FFFFF: Video memory, which occupies the highest 32K in RAM.
*    - $FC0000 - $FCFFFF: Memory-mapped I/O.
*    - $FE0000 - $FEFFFF: "Special I/O space".
*
* (Address ranges not shown are unmapped/not in use.)
*
* **Parts:** The four parts of the bootloader are:
*
*    - `StageOne`: loads `StageTwo` and `Relocator`; jumps to `Relocator`
*    - Hard drive I/O library: used by `StageOne` and `StageTwo`
*    - `StageTwo`: loads the program and jumps to it
*    - `Relocator`: copies the Drive I/O library and `StageTwo` to the top of
*          free RAM; jumps to `StageTwo`
*
* `StageOne` and the I/O library fill the first block ($000000) of the hard
* drive and are the only parts of the bootloader that are loaded into memory by
* system ROMs; the remaining parts occupy the second block ($000001) and must
* be retrieved from disk by the bootloader.
*
* The `Relocator` routine is necessary because the Lisa boot ROM copies the
* executable part of the first hard drive block (bytes $14 and on) to memory
* addresses $20000-$201FF. (Similarly, the parallel port expansion card ROM
* copies this same data to $20810-$20A0F.) So, to maximise the available
* program space in free RAM, `Relocator` copies `StageTwo` and the I/O library
* to the highest possible address in free RAM (i.e. just below the video
* memory).
*
* From there, `StageTwo` loads program data $200 bytes at a time from block
* $000002 onward, depositing the result in RAM from address $800. Each block
* is appended to the program data loaded so far, but because the 20-byte block
* tag precedes the block's program data, more processing is required. The
* `HandleTag` subroutine exchanges the order of the block's program data and
* tag, verifies the checksum of the program data, and detects whether the tag
* contains the special "final block" string defined at `BlockOne`. If so,
* `StageTwo` stops loading blocks and jumps to $800.
*
*
* Software dependencies for building the bootloader
* -------------------------------------------------
*
* As noted, the bootloader uses the `lisa_profile_io.x68` component from the
* `lisa_io` software library project at https://github.com/stepleton/lisa_io .
* If not there already, place this file in a subdirectory of the top-level
* directory called `lisa_io` before attempting to build the bootloader.
*
* Windows users may need to change the '/' in the INCLUDE directive for this
* component to a '\'.
*
*
* Building the bootloader
* -----------------------
*
* The bootloader is written in the dialect of 68000 macro assembly supported
* by the open-source Windows-only EASy68K development environment and simulator
* (http://www.easy68k.com/). Converting its source code to a dialect compatible
* with other popular assemblers should not be very difficult.
*
* There is a standalone version of the EASy68K assembler that is usable from a
* Unix command line (https://github.com/rayarachelian/EASy68K-asm). All
* bootloader development work used this assembler, and users who don't want to
* use a different assembly dialect are recommended to use it themselves.
*
* Either assembler compiles this bootloader's code to a Motorola S-Record file
* (`lisa_profile_io.S68` by default). You can convert the S-Record file into
* raw binary code with the `EASyBIN.exe` program distributed with EASy68K, or
* with the `srec_cat` program distributed with the SRecord package for UNIX
* systems (http://srecord.sourceforge.net/), among many other options.  An
* example invocation of `srec_cat` is:
*
*    srec_cat bootloader_hd.S68 -ignore_checksums -o bootloader_hd.bin -bin
*
* (The `-ignore_checksums` flag may be required by differences in the way
* EASy68K and the command-line assembler compute checksums.)
*
*
* Resources
* ---------
*
* The following resources were used to develop this bootloader:
*
*    - [EASy68K-asm](https://github.com/rayarachelian/EASy68K-asm): a 68000
*      assembler derived from the [EASy68K development environment and
*      simulator](http://www.easy68k.com/) by Ray Arachelian.
*
*    - [lisaem](http://lisaem.sunder.net/): Apple Lisa emulation for
*      development and testing, as well as information (gleaned from the source
*      code) about interfacing the with I/O board and expansion card VIAs.
*
*    - [Lisa Boot ROM Manual v1.3](http://bitsavers.informatik.uni-stuttgart.de/pdf/apple/lisa/Lisa_Boot_ROM_Manual_V1.3_Feb84.pdf):
*      Lisa boot ROM documentation (nb: some information appears not to be
*      current; refer to ROM source listing for more reliable information).
*
*    - [Lisa_Boot_ROM_Asm_Listing.TEXT](http://bitsavers.informatik.uni-stuttgart.de/pdf/apple/lisa/firmware/Lisa_Boot_ROM_Asm_Listing.TEXT):
*      Authoritative information for boot ROM version H.
*
*    - [Apple Lisa Computer: Hardware Manual -- 1983 (with Errata)](http://lisa.sunder.net/LisaHardwareManual1983.pdf):
*      Extensive details on Apple Lisa internals.
*
* As is often the case, assistance from Ray Arachelian and technical resources
* archived at bitsavers.org are gratefully acknowledged.
*
*
* Revision history
* ----------------
*
* This section records the development of this file as part of the
* `bootloader_hd` project at <http://github.com/stepleton/bootloader_hd>.
*
* 30 March 2020: Initial release.
* (Tom Stepleton, stepleton@gmail.com, London)


    ORG     $0                     ; The code begins in disk block 0

BlockZero:
    ; Here are the 20 tag bytes for the disk's first block. As far as the Lisa
    ; boot ROM is concerned, it's only important that the fifth and sixth bytes
    ; of this tag be $AA; the rest of the tag is ignored.
    ;
    ; Geeking out further, note that for Widget drives, Lisa filesystems
    ; usually store tags at the ends of 532-byte blocks, not the beginnings.
    ; The boot ROM does not honour this convention, and neither will this
    ; bootloader for that matter.
    DC.B    'Yo! ',$AA,$AA,' I',$27,'m bootable!'

StageOne:
    ; Now we begin the actual code. The Lisa boot ROM will install the data
    ; bytes of this block at location $20000, but our code is relocatable, so
    ; we don't care.
    MOVE.B  $1B3,D0                ; Boot device ID saved by the ROM into D0
    BSR.S   ProFileIoSetup         ; Set up the parallel port for that device
    BSR.W   ProFileIoInit          ; Initialise the VIAs (or VIA, for exp.cards)
    ; We don't check whether ProFileIoInit found a drive connected to the port
    ; specified by $1B3---the fact that we booted from the drive is a big clue.

    MOVEQ.L #$40,D1                ; The command $00000100 means: read block...
    LSL.L   #$02,D1                ; ...$000001 from the drive
    MOVE.W  #$0A03,D2              ; Our retry count and sparing threshold
    LEA.L   BlockOne(PC),A0        ; We'll save loaded data at BlockOne
    BSR.W   ProFileIo              ; Try to load that data!
    BEQ.W   Relocator              ; Loaded, now execute it
    TRAP    #$00                   ; Didn't load; fail with a misc error

ProFileLib:
    INCLUDE lisa_io/lisa_profile_io.x68  ; Relocatable ProFile I/O library



    ORG     $214                   ; The code continues in disk block 1

BlockOne:
    ; Here are the 20 tag bytes for the disk's second block. These bytes are
    ; also the prototype for the tag bytes that mark the last block that the
    ; bootloader should load from the hard drive. In other words, the bootloader
    ; will merrily load block after block from the drive into RAM until it
    ; encounters one whose tag ends with the first 18 bytes of the tag seen
    ; below (i.e. through the first $00 byte). The initial two tag bytes in each
    ; loaded block should be a 16-bit checksum of the block's data bytes for
    ; checking correct loading, computed the same way the boot ROM computes it.
    DC.B    ' bit.ly/3arucNJ  ',$00,$00,$00
    ; (Note that the `build_bootable_disk_image.py` script won't allow use of
    ; lowercase letters in tags, so this tag is a distinct, dependable marker.)

StageTwo:
    MOVEA.W #$800,A0               ; We will load ProFile data starting here

    ; The first part of the loop loads and checks the block.
.lp ADD.L   D7,D1                  ;   D1 now says to load the next block
    BSR.W   ProFileIo              ;   Load it
    BNE.S   .no                    ;   Did not load! Branch to fail
    BSR.S   HandleTag              ;   Rearrange/analyse/maybe print block tag
    BEQ.S   .go                    ;   Was it the last tag? Start the code

    ; The second part of the loop shows the block tag to the user.
    CLR.B   $12(A0)                ;   Add null terminator after tag to be safe
    MOVEM.L D1-D2/D7/A0,-(SP)      ;   Save registers prior to prepping the call
    LEA.L   $02(A0),A3             ;   Point to the tag to print it
    MOVEQ.L #$0D,D5                ;   Print it on row 13
    MOVEQ.L #$18,D6                ;   Starting at column 24
    MOVEQ.L #$18,D4                ;   Newlines continue from column 24
    JSR     $FE0088                ;   Call the printing routine
    MOVEM.L (SP)+,D1-D2/D7/A0      ;   Restore registers we care about

    BRA.S   .lp                    ;   Loop again to load the next block

    ; If the loaded code wants, it can refer to our ProFile I/O library routines
    ; at the addresses saved in the first three address registers.
.go LEA.L   ProFileIoSetup(PC),A0
    LEA.L   ProFileIoInit(PC),A1
    LEA.L   ProFileIo(PC),A2
    LEA.L   zProFileErrCode(PC),A3
    JMP     $800                   ; That's it! Farewell, off to the loaded code

    ; We've failed to load a block; show an error message that also lists the
    ; block we tried to load and return to the ROM.
.no LEA.L   sIoError(PC),A3        ; Arg: here's the message to write
    BRA.S   ErrorQuit              ; Show the message and quit to the ROM


    ; HandleTag -- Swap a block's tag and data, check checksum, look for end tag
    ; Args:
    ;   A0: Points just past the end of the block to process     
    ; Notes:
    ;   Sets Z if the block just loaded has a tag marking it as the last block
    ;   Will not return (fails to ROM) if a block's data checksum (as computed
    ;       by the ROM checksum routine at $FE00BC) is not the two's complement
    ;       of the first two tag bytes
    ;   On return, A0 will point just past the end of the data bytes, which is
    ;       is also the beginning of the tag bytes
    ;   Trashes D0/D3/A0-A6, guaranteed NOT to trash D1, D2, or D7
HandleTag:
    ; First, we swap the order of the data bytes and the tag bytes. We do this
    ; without using any temporary memory space.
    SUBA.W  #$0214,A0              ; Rewind A0 to the start of the loaded block
    MOVEA.L A0,A1                  ; Copy A0 to A1
    MOVEM.L (A1)+,A2-A6            ; Copy all tag bytes to A2-A6, advancing A1!
    MOVEQ.L #$7F,D0                ; Set up loop counter for shifting data longs
.dl MOVE.L  (A1)+,(A0)+            ;   Copy a data word
    DBRA    D0,.dl                 ;   Loop to copy the next word
    MOVEM.L A2-A6,(A0)             ; Now append the tag bytes to the data bytes

    ; Now we check the checksum of this loaded block using the utility routine
    ; in the boot ROM. The 16-bit block checksum is kept in the first two bytes
    ; of the tag, which is where the ROM routine wants to find it: that is, just
    ; after the data it's checking.
    MOVEM.L D1-D2/D7/A0,-(SP)      ; Save registers prior to preparing the call
    SUBA.W  #$0200,A0              ; Arg: rewind A0 to the start of the sctor
    MOVE.W  #$0100,D0              ; Arg: D0 is the number of words to check - 1
    CLR.W   D1                     ; Arg: check regular memory
    JSR     $FE00BC                ; Jump to the checksum routine
    MOVEM.L (SP)+,D1-D2/D7/A0      ; Restore registers we care about
    BCS.S   .no                    ; Jump to fail on checksum mismatch

    ; Now we check whether the tag marks this block as the last block to load
    ; from disk.
    LEA.L   $02(A0),A1             ; Now to compare the block tag at (A0)+2...
    LEA.L   BlockOne(PC),A2        ; ...with the prototype at (A2)
.tl MOVE.B  (A2)+,D0               ;   Copy expected next byte to D0
    CMP.B   (A1)+,D0               ;   Is the tag byte byte the same?
    BNE.S   .rt                    ;   No, so jump to return to the caller
    TST.B   D0                     ;   Was this the null terminator?
    BNE.S   .tl                    ;   No, onward to the next byte
.rt RTS                            ; And back to the caller with Z set correctly

    ; We've got a checksum mismatch; show an error message that also lists the
    ; bad block and return to the ROM.
.no LEA.L   sBadChecksum(PC),A3    ; Arg: here's the message to write
    ; And fall through to the shared code for displaying errors.


    ; ErrorQuit -- Quit to ROM, showing an error message and the current block
    ; Args:
    ;   D1: ProFileIo block-and-command arg for a block where an error occurred
    ;   A3: Error string to display to the user
    ; Notes:
    ;   Not really a subroutine; don't BSR/JSR here
    ;   Block addresses are three bytes, but ROM error messages will only show
    ;       the last two bytes of the address
    ;   (But this boot loader won't ever load beyond block $0000F64 anyway, and
    ;       only that far if the Lisa has 2MB of RAM)
    ;   Never returns
ErrorQuit:
    MOVE.L  D1,D0                  ; Arg: show the block that had the error...
    LSR.L   #$08,D0                ; ...only LSWord is shown (that's OK)
    SUBA.L  A2,A2                  ; Arg: there's no icon to show
    JSR     $FE0084                ; Call: return to the ROM with an error


sIoError:
    DC.B    'READ ERROR... SECTOR NUM SHOWN IN ERROR CODE',$00
sBadChecksum:
    DC.B    'BAD CHECKSUM... SECTOR NUM SHOWN IN ERROR CODE',$00

    DS.W    0                      ; For alignment


    ; Relocator -- copy I/O library, Stage Two to top of RAM; jump to Stage Two
    ; Args:
    ;   D1: The value $00000100
    ; Notes:
    ;   Not really a subroutine; don't BSR/JSR here
    ;   D1, the command to read block $000001, is copied to D7 to serve as the
    ;       increment to D1 for reads from successive blocks
    ;   Trashes D0/D7/A0-A1, guaranteed NOT to trash D1 or D2
    ;   Never returns; jumps into Stage 2 instead
Relocator:
    ; The relocator will copy the I/O library and the stage two code to the top
    ; of the memory, just underneath the area being used for the screen bitmap.
    ; First we figure out where that is.
    MOVE.W  #(Relocator-ProFileLib),D0   ; Our size into D0
    MOVEA.L $2A8,A0                ; "End of memory" saved by the ROM into A0
    ADDA.W  #$8000,A0              ; Less 32k (screen) (note: sign extension!)
    SUBA.W  D0,A0                  ; Less our size, and that's it
    LEA.L   ProFileLib(PC),A1      ; Here's where to copy from
    SUBQ.W  #$01,D0                ; Set up the loop counter for copying
.lp MOVE.B  (A1)+,(A0)+            ;   Copy a byte
    DBRA    D0,.lp                 ;   Loop to copy another

    ; Before we jump to Stage Two, we also copy the old read block command
    ; ($00000100) to D7. We do this because this value is also the value we
    ; want to keep adding to D1 to get it to specify the next block.
    MOVE.L  D1,D7                  ; Save block increment

    ; We're ready now to jump to the copy of StageTwo we put in high memory,
    ; leaving this relocator behind to be overwritten.
    SUBA.W  #(Relocator-StageTwo),A0   ; Rewind A0 to the start of StageTwo
    JMP     (A0)                   ; Now jump there


    END     StageOne
