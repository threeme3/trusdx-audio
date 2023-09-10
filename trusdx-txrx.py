#!/usr/bin/env python3
# de SQ3SWF, PE1NNZ 2023

# Linux:
# sudo apt install portaudio19-dev
# stty -F /dev/ttyUSB0 raw -echo -echoe -echoctl -echoke -hupcl 115200;
# pactl load-module module-null-sink sink_name=TRUSDX sink_properties=device.description="TRUSDX"
# pavucontrol
###

# Windows 7:
# Install python3.6 (32 bits version)
# python -m pip install --upgrade pip
# python -m pip install pyaudio   # or download and install the matching version from: https://www.lfd.uci.edu/~gohlke/pythonlibs/#pyaudio
# python -m pip install pyaudio
# Install, extract VB-Audio Virtual Audio Cable from https://download.vb-audio.com/
# Install VB-Audio by clicking right on x64 executable and select Run as Administrator, click install driver
# Download and extract com0com from https://sourceforge.net/projects/com0com/
# setup.exe /S /D=C:\Program Files\com0com
# Install x64 executable. In case of driver-signing issues: every-time reboot Windows by holding F8 (Win7) or Shift (Win8/10), select "Disable Driver Signature Enforcement" in Advanced Boot options
# Select Start > com0com > Setup Command Prompt, and enter: uninstall > enter: install PortName=COM8 PortName=COM9
# or open Command Prompt > cd C:\Program Files (x86)\com0com > setupc install PortName=COM8 PortName=COM9
# Select CABLE audio devices and COM8 in WSJT-X or any other HAM radio program

# Build: sudo apt install patchelf && python -m pip install -U nuitka
# python -m nuitka --standalone trusdx-txrx.py

# Setup_com0com_v3.0.0.0_W7_x64_signed.exe  /S /D=C:\Program Files\com0com
# cd "c:\Program Files\com0com"
# setupc.exe install PortName=COM8 PortName=COM9
# (as admin) VBCABLE_Setup_x64.exe

###
# socat -d -d pty,link=/tmp/ttyS0,echo=0,ignoreeof,b115200,raw,perm=0777 pty,link=/tmp/ttyS1,echo=0,ignoreeof,b115200,raw,perm=0777 &
# sudo modprobe snd-aloop

import pyaudio
import serial
import serial.tools.list_ports
import threading
import time
import os
import datetime
import array
import argparse
from sys import platform

audio_tx_rate_trusdx = 4800
audio_tx_rate = 11520  #11521
audio_rx_rate = 7812
buf = []    # buffer for received audio
urs = [0]   # underrun counter
status = [False, False, True, False, False]	# tx_state, cat_streaming_state, running, cat_active, keyed_by_rts_dtr

def log(msg):
    if config['verbose']: print(f"{datetime.datetime.utcnow()} {msg}")

def show_audio_devices():
    for i in range(pyaudio.PyAudio().get_device_count()):
        print(pyaudio.PyAudio().get_device_info_by_index(i))
    for i in range(pyaudio.PyAudio().get_host_api_count()):
        print(pyaudio.PyAudio().get_host_api_info_by_index(i))
        
def find_audio_device(name, occurance = 0):
    if platform == "linux" or platform == "linux2": return -1  # not supported
    result = [i for i in range(pyaudio.PyAudio().get_device_count()) if name in (pyaudio.PyAudio().get_device_info_by_index(i)['name']) ]
    return result[occurance] if len(result) else -1 # return n-th matching device to name, -1 for no match

def show_serial_devices():
    for port in serial.tools.list_ports.comports():
        print(port)

def find_serial_device(name, occurance = 0):
    result = [port.device for port in serial.tools.list_ports.comports() if name in port.description]
    return result[occurance] if len(result) else "" # return n-th matching device to name, "" for no match

def handle_rx_audio(ser, cat, pastream, d):
    if status[1]:
        #log(f"stream: {d}")
        if not status[0]: buf.append(d)                   # in CAT streaming mode: fwd to audio buf
        #if not status[0]: pastream.write(d)  #  in CAT streaming mode: directly fwd to audio
        if d[-1] == ord(';'):
            status[1] = False           # go to CAT cmd mode when data ends with ';'
            #log("***CAT mode")
    else:
        if d.startswith(b'US'):
            #log("***US mode")
            status[1] = True            # go to CAT stream mode when data starts with US
        else:
            if status[3]:               # only send something to cat port, when active
                cat.write(d)
                cat.flush()
                log(f"O: {d}")  # in CAT command mode
            else:
                log("Skip CAT response, as CAT is not active.")

def receive_serial_audio(ser, cat, pastream):
    try:
        log("receive_serial_audio")
        bbuf = b''  # rest after ';' that cannot be handled
        while status[2]:
            if False and status[0]:  # WORKAROUND: special case for TX; this is a workaround to handle CAT responses properly during TX
                if(ser.in_waiting < 1): time.sleep(0.001)
                else:
                    d = ser.read()
                    #log(f"Q: {d}")  # in TX CAT command mode
                    #cat.write(d)
                    #cat.flush()
                    handle_rx_audio(ser, cat, pastream, d)
            # below implements: d = ser.read_until(b';', 32)  #read until CAT end or enough in buf but only up to 32 bytes to keep response
            #elif(ser.in_waiting < config['tx_block_size']): time.sleep(0.001)   #normal case for RX
            elif(ser.in_waiting == 0): time.sleep(0.001)   #normal case for RX
            else:
                #d = bbuf + ser.read(config['tx_block_size'])
                d = bbuf + ser.read(ser.in_waiting)
                x = d.split(b';', maxsplit=1)
                cat_delim = (len(x) == 2)
                bbuf = x[1] if cat_delim else b''
                if not cat_delim and len(x[0]) < config['tx_block_size']:
                    bbuf = x[0]
                    continue
                d = x[0] + b';' if cat_delim else x[0]
                handle_rx_audio(ser, cat, pastream, d)
    except Exception as e:
        log(e)
        status[2] = False
        if config['verbose']: raise

def play_receive_audio(pastream):
    try:
        log("play_receive_audio")
        while status[2]:
            if len(buf) < 2:
                #log(f"UNDERRUN #{urs[0]} - refilling")
                urs[0] += 1
                while len(buf) < 10:
                    time.sleep(0.001)
            if not status[0]: pastream.write(buf[0])
            buf.remove(buf[0])
    except Exception as e:
        log(e)
        status[2] = False
        if config['verbose']: raise

def tx_cat_delay(ser):
    #ser.reset_output_buffer() # because trusdx TX buffers can be full, empty host buffers (but reset_output_buffer does not seem to work)
    ser.flush()  # because trusdx TX buffers can be full, wait until all buffers are empty
    #time.sleep(0.003 + config['block_size']/audio_tx_rate) # time.sleep(0.01) and wait a bit before interrupting TX stream for a CAT cmd
    #time.sleep(0.0005 + 32/audio_tx_rate_trusdx) # and wait until trusdx buffers are read
    time.sleep(0.010) # and wait a bit before interrupting TX stream for a CAT cmd

def handle_vox(samples8, ser):
    if (128 - min(samples8)) == 64 and (max(samples8) - 127) == 64: # if does contain very loud signal
        if not status[0]:
            status[0] = True
            #log("***TX mode")
            ser.write(b";TX0;")
            ser.flush()
    elif status[0]:  # in TX and no audio detected (silence)
        tx_cat_delay(ser)
        ser.write(b";RX;")
        ser.flush()
        status[0] = False
        #log("***RX mode")

def handle_rts_dtr(ser, cat):
    if not status[4] and (cat.cts or cat.dsr):
        status[4] = True    # keyed by RTS/DTR
        status[0] = True
        #log("***TX mode")
        ser.write(b";TX0;")
        ser.flush()
    elif status[4] and not (cat.cts or cat.dsr):  #if keyed by RTS/DTR
        tx_cat_delay(ser)
        ser.write(b";RX;")
        ser.flush()
        status[4] = False
        status[0] = False
        #log("***RX mode")
    
def handle_cat(pastream, ser, cat):
    if(cat.inWaiting()):
        if not status[3]:
            status[3] = True
            log("CAT interface active")
        d = cat.read_until(b";")
        if True and d.startswith(b'ID'):   # this is a workaround for unrealistic fast RTT expectations in hamlib for sequence RX;ID;
            cat.write(b'ID020;')
            log(f"I: {d}")
            log(f"O: ID020; (emu)")
            return
        if status[0]:
            #log("***;")
            tx_cat_delay(ser)
            ser.write(b";")  # in TX mode, interrupt CAT stream by sending ; before issuing CAT cmd
            ser.flush()
        log(f"I: {d}")
        ser.write(d)                # fwd data on CAT port to trx
        ser.flush()
        if d.startswith(b"TX"):
           status[0] = True
           #log("***TX mode")
           #ser.reset_input_buffer()
           pastream.stop_stream()
           pastream.start_stream()
           pastream.read(config['block_size'], exception_on_overflow = False)
        if d.startswith(b"RX"):
           status[0] = False
           pastream.stop_stream()
           pastream.start_stream()
           #log("***RX mode")

def transmit_audio_via_serial(pastream, ser, cat):
    try:
        log("transmit_audio_via_serial_cat")
        while status[2]:
            handle_cat(pastream, ser, cat)
            if(platform == "win32" and not config['no_rtsdtr']): handle_rts_dtr(ser, cat)
            if (status[0] or config['vox']) and pastream.get_read_available() > 0:    # in TX mode, and audio available
                samples = pastream.read(config['block_size'], exception_on_overflow = False)
                arr = array.array('h', samples)
                samples8 = bytearray([128 + x//256 for x in arr])  # was //512 because with //256 there is 5dB too much signal. Win7 only support 16 bits input audio -> convert to 8 bits
                samples8 = samples8.replace(b'\x3b', b'\x3a')      # filter ; of stream
                if status[0]: ser.write(samples8)
                if config['vox']: handle_vox(samples8)
            else:
                time.sleep(0.001)
    except Exception as e:
        log(e)
        status[2] = False
        if config['verbose']: raise

def pty_echo(fd1, fd2):
    try:
        log("pty_echo")
        while status[2]:
            c1 = fd1.read(1)
            fd2.write(c1)
            #print(f'{datetime.datetime.utcnow()} {threading.current_thread().ident} > ', c1)
    except Exception as e:
        log(e)
        status[2] = False
        if config['verbose']: raise

# https://stackoverflow.com/questions/7088672/pyaudio-working-but-spits-out-error-messages-each-time
def run():
    try:
        status[0] = False
        status[1] = False
        status[2] = True
        status[3] = False
        status[4] = False

        if platform == "linux" or platform == "linux2":
           virtual_audio_dev_out = ""#"TRUSDX"
           virtual_audio_dev_in  = ""#"TRUSDX"
           trusdx_serial_dev     = "USB Serial"
           loopback_serial_dev   = ""
           cat_serial_dev        = ""
           alt_cat_serial_dev    = "/tmp/trusdx"
        elif platform == "win32":
           virtual_audio_dev_out = "CABLE Output"
           virtual_audio_dev_in  = "CABLE Input"
           trusdx_serial_dev     = "CH340"
           loopback_serial_dev   = "COM9"
           cat_serial_dev        = "COM8"
        elif platform == "darwin":
           virtual_audio_dev_out = "BlackHole 2ch"
           virtual_audio_dev_in  = "BlackHole 2ch"
           trusdx_serial_dev     = "USB Serial"
           loopback_serial_dev   = ""
           cat_serial_dev        = ""

        if config['direct']:
           virtual_audio_dev_out = "" # default audio device
           virtual_audio_dev_in  = "" # default audio device

        if config['verbose']:
            show_audio_devices()
            print("Audio device = ", find_audio_device(virtual_audio_dev_in), find_audio_device(virtual_audio_dev_out) )
            show_serial_devices()
            print("Serial device = ", find_serial_device(trusdx_serial_dev) )
            print("Serial loopback = ", find_serial_device(loopback_serial_dev) )
        
        if platform == "win32":
            if find_serial_device(loopback_serial_dev):
                print(f"Conflict on COM port {loopback_serial_dev}: Go to Device Manager, select CH340 device and change in advanced settings COM port other than 8 or 9.")
                time.sleep(1)
            if find_serial_device(cat_serial_dev):
                print(f"Conflict on COM port {cat_serial_dev}: Go to Device Manager, select CH340 device and change in advanced settings COM port other than 8 or 9.")
                time.sleep(1)

        if platform != "win32":  # skip for Windows as we have com0com there
           _master1, slave1 = os.openpty()  # make a tty <-> tty device where one end is opened as serial device, other end by CAT app
           _master2, slave2 = os.openpty()
           master1 = os.fdopen(_master1, 'rb+', 0)
           master2 = os.fdopen(_master2, 'rb+', 0)
           threading.Thread(target=pty_echo, args=(master1,master2)).start()
           threading.Thread(target=pty_echo, args=(master2,master1)).start()
           cat_serial_dev = os.ttyname(slave1)
           #if os.path.exists(alt_cat_serial_dev): os.remove(alt_cat_serial_dev)
           #os.symlink(cat_serial_dev, alt_cat_serial_dev)
           #print(f"Redirected {alt_cat_serial_dev} CAT port to driver.")
           loopback_serial_dev = os.ttyname(slave2)
        try:
            ser2 = serial.Serial(loopback_serial_dev, 115200, write_timeout = 0)
        except Exception as e:
            if platform == "win32":
                print("VSPE virtual com port not found: reinstall or enable")
            else:
                print("/dev/pts/x device not found")
        
        try:
           in_stream = pyaudio.PyAudio().open(frames_per_buffer=0, format = pyaudio.paInt16, channels = 1, rate = audio_tx_rate, input = True, input_device_index = find_audio_device(virtual_audio_dev_out) if virtual_audio_dev_out else -1)
           out_stream = pyaudio.PyAudio().open(frames_per_buffer=0, format = pyaudio.paUInt8, channels = 1, rate = audio_rx_rate, output = True, output_device_index = find_audio_device(virtual_audio_dev_in) if virtual_audio_dev_in else -1)
        except Exception as e:
            if platform == "win32": print("VB-Audio CABLE not found: reinstall or enable")
            else:
                print("port audio device not found: ")
                print("  run in terminal: pactl load-module module-null-sink sink_name=TRUSDX sink_properties=device.description=\"TRUSDX\" && pavucontrol  (hint: sudo modprobe snd-aloop)")
            raise
 
        try:
            ser = serial.Serial(find_serial_device(trusdx_serial_dev), 115200, write_timeout = 0)
        except Exception as e:
            print("truSDX device not found")
            raise
            
        #ser.dtr = True
        #ser.rts = False
        time.sleep(3) # wait for device to start after opening serial port
        ser.write(b";MD2;UA2;" if not config['unmute'] else b";MD2;UA1;") # enable audio streaming, mute trusdx
        #status[1] = True

        threading.Thread(target=receive_serial_audio, args=(ser,ser2,out_stream)).start()
        threading.Thread(target=play_receive_audio, args=(out_stream,)).start()
        threading.Thread(target=transmit_audio_via_serial, args=(in_stream,ser,ser2)).start()

        print(f"(tr)uSDX driver OK! Available devices = [{virtual_audio_dev_in}, {virtual_audio_dev_out}, {cat_serial_dev}]" )
        #ts = time.time()
        while status[2]:    # wait and idle
            # display some stats every 1 seconds
            #log(f"{int(time.time()-ts)} buf: {len(buf)}")
            time.sleep(1)
    except Exception as e:
        log(e)
        status[2] = False
    except KeyboardInterrupt:
        print("Stopping")
        status[2] = False
        ser.write(b";UA0;")

    try:
        # clean-up
        log("Closing")
        time.sleep(1)   
        if platform != "win32":  # Linux
           #master1.close()
           #master2.close()
           #os.close(_master1)           
           os.close(slave1)
           #os.close(_master2)
           os.close(slave2)
           log("fd closed")
        ser2.close()
        ser.close()
        #in_stream.close()
        #out_stream.close()
        pyaudio.PyAudio().terminate()
        log("Closed")
    except Exception as e:
        log(e)
        pass	

def main():
    #print("(tr)uSDX audio driver")
    while 1:
        run();

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="(tr)uSDX audio driver", formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true", default=False, help="increase verbosity")
    parser.add_argument("--vox", action="store_true", default=False, help="VOX audio-triggered PTT (Linux only)")
    parser.add_argument("--unmute", action="store_true", default=False, help="Enable (tr)usdx audio")
    parser.add_argument("--direct", action="store_true", default=False, help="Use system audio devices (no loopback)")
    parser.add_argument("--no-rtsdtr", action="store_true", default=False, help="Disable RTS/DTR-triggered PTT")
    #parser.add_argument("-B", "--block-size", type=int, default=512 if platform == "win32" else 32, help="RX Block size")
    parser.add_argument("-B", "--block-size", type=int, default=512, help="RX Block size")
    parser.add_argument("-T", "--tx-block-size", type=int, default=48, help="TX Block size")
    args = parser.parse_args()
    config = vars(args)
    if config['verbose']: print(config)

    #try:
    main()
    #except Exception as e:
    #    print(f"Error: {e}")
    #    time.sleep(3)
