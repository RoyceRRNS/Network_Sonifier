"""Live traffic for Network-Sonifier.html (Windows).

    python live_capture.py

Reads the headers of this computer's own network packets as they pass and streams them to the
sonifier page, which it serves at http://127.0.0.1:8765/ to this computer only. Nothing is saved
and nothing is sent anywhere else. Windows only lets an administrator read packets, so the script
asks to be started again as one. Close its window to stop.

Needs nothing beyond Python 3: packets are read with a raw socket, not with Wireshark or Npcap.
"""
import base64, collections, ctypes, http.server, json, os, socket, sys, threading, time, webbrowser

PORT = 8765
URL = f'http://127.0.0.1:{PORT}/#live'
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Network-Sonifier.html')
pages = set()   # the open pages' requests, each with a queue of packets not yet sent to it


def publish(data, out):
    """Queue one IP packet for the open pages: its time, direction, length and header bytes."""
    head = (data[0] & 15) * 4 + 20 if data[0] >> 4 == 4 else 60   # the IP header and the start of TCP or UDP, not the payload
    record = [round(time.time(), 4), int(out), len(data), base64.b64encode(data[:head]).decode()]
    for page in list(pages):
        page.queue.append(record)


def route_address(family):
    """This computer's address on the network that carries its default route, or None while there is none."""
    probe = socket.socket(family, socket.SOCK_DGRAM)
    try:
        # Connecting a UDP socket only looks the route up: no packet is sent. The targets are documentation addresses.
        probe.connect(('192.0.2.1' if family == socket.AF_INET else '2001:db8::1', 9))
        return probe.getsockname()[0]
    except OSError:
        return None
    finally:
        probe.close()


def sniff(family):
    """Read every IPv4 or IPv6 packet on that network, starting again whenever the network changes."""
    v4 = family == socket.AF_INET
    source = slice(12, 16) if v4 else slice(8, 24)
    while True:
        address = route_address(family)
        if not address:
            time.sleep(1)
            continue
        mine = {socket.inet_pton(family, a[4][0].split('%')[0]) for a in socket.getaddrinfo(socket.gethostname(), None, family)}
        s = socket.socket(family, socket.SOCK_RAW, socket.IPPROTO_IP if v4 else socket.IPPROTO_IPV6)
        try:
            s.bind((address, 0))
            s.ioctl(socket.SIO_RCVALL, socket.RCVALL_ON)
            s.settimeout(1)
            print('Reading packets on', address)
            while True:
                try:
                    data = s.recv(65535)
                except socket.timeout:
                    if route_address(family) != address:   # a silent second is the moment to check the network is still the same
                        break
                    continue
                if data[0] >> 4 == (4 if v4 else 6):   # only a packet that starts with its IP header
                    publish(data, data[source] in mine)
        except OSError as e:
            print(f'Stopped reading on {address}: {e}')
            time.sleep(1)
        finally:
            s.close()


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get('Host') not in (f'127.0.0.1:{PORT}', f'localhost:{PORT}'):   # a page on this computer, asked for by its real address
            self.send_error(403)
        elif self.path == '/live':
            self.stream()
        elif self.path == '/':
            with open(PAGE, 'rb') as f:
                body = f.read()
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_error(404)

    def stream(self):
        """Server-sent events: one batch of packets every 50 ms. Empty batches show the page that the feed is alive."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.queue = collections.deque(maxlen=50000)   # a page that falls behind loses the oldest packets
        pages.add(self)
        try:
            while True:
                time.sleep(0.05)
                batch = [self.queue.popleft() for _ in range(len(self.queue))]
                self.wfile.write(b'data: ' + json.dumps(batch, separators=(',', ':')).encode() + b'\n\n')
        except OSError:   # the page was closed
            pass
        finally:
            pages.discard(self)

    def log_message(self, *args):
        pass


def serve():
    server = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), Handler)
    for family in (socket.AF_INET, socket.AF_INET6):
        threading.Thread(target=sniff, args=(family,), daemon=True).start()
    print(f'Live traffic page: {URL}\nClose this window to stop.')
    server.serve_forever()


def running():
    try:
        socket.create_connection(('127.0.0.1', PORT), 0.3).close()
        return True
    except OSError:
        return False


if __name__ == '__main__':
    shell = ctypes.windll.shell32
    if running():                 # already started: only the page is needed
        webbrowser.open(URL)
    elif shell.IsUserAnAdmin():
        serve()
    # Otherwise start this script again as administrator (Windows asks first) and open the page from here,
    # so that the browser itself does not run as administrator.
    elif shell.ShellExecuteW(None, 'runas', sys.executable, f'"{os.path.abspath(__file__)}"', None, 1) > 32:
        for _ in range(50):
            if running():
                break
            time.sleep(0.2)
        webbrowser.open(URL)
