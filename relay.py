import socket, os, sys, time, subprocess, select, signal

T = "/data/data/com.termux/files/usr"
H = "/data/data/com.termux/files/home"
SOCK = "/data/vendor/wifi/wpa/sockets/"
PIDF = "/data/local/tmp/dnsmasq-p2p.pid"
WPID = "/data/local/tmp/relay.watcher.pid"
STATE = "/data/local/tmp/relay.iface"
NET = "192.168.49"
ENV = dict(os.environ)
ENV["LD_LIBRARY_PATH"] = T + "/lib"


def sh(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=ENV)
    return (r.stdout + r.stderr).strip()


def readf(p):
    try:
        return open(p).read().strip()
    except Exception:
        return ""


def get_freq():
    for line in sh(T + "/bin/iw dev wlan0 link").splitlines():
        line = line.strip()
        if line.startswith("freq:"):
            try:
                return int(float(line.split(":")[1].strip()))
            except Exception:
                return None
    return None


def wpa(cmds):
    for f in os.listdir(SOCK):
        if f.startswith("ev_"):
            try:
                os.unlink(SOCK + f)
            except Exception:
                pass
    local = SOCK + "ev_%d" % os.getpid()
    s = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    s.bind(local)
    os.chmod(local, 0o777)
    lines = []
    dest = SOCK + "p2p-dev-wlan0"
    sh("setenforce 0")
    try:
        s.sendto(b"ATTACH", dest)
        time.sleep(1)
        for c, pause in cmds:
            s.sendto(c.encode(), dest)
            end = time.time() + pause
            while time.time() < end:
                if select.select([s], [], [], 0.5)[0]:
                    lines.append(s.recv(4096).decode().strip())
        s.sendto(b"DETACH", dest)
    finally:
        s.close()
        try:
            os.unlink(local)
        except Exception:
            pass
        sh("setenforce 1")
    return lines


def p2p_ifaces():
    return [n for n in os.listdir("/sys/class/net") if n.startswith("p2p-wlan0-")]


def stop_all():
    pid = readf(PIDF)
    if pid:
        sh("kill " + pid)
    ifaces = p2p_ifaces()
    saved = readf(STATE)
    if saved and saved not in ifaces:
        ifaces.append(saved)
    sh("ip rule del pref 999")
    sh("ip rule del pref 1000")
    sh("iptables -w -t nat -D POSTROUTING -s %s.0/24 -o wlan0 -j MASQUERADE" % NET)
    for i in ifaces:
        sh("iptables -w -D INPUT -i %s -j ACCEPT" % i)
        sh("iptables -w -D FORWARD -i %s -o wlan0 -j ACCEPT" % i)
        sh("iptables -w -D FORWARD -i wlan0 -o %s -m state --state ESTABLISHED,RELATED -j ACCEPT" % i)
    live = p2p_ifaces()
    if live:
        wpa([("P2P_GROUP_REMOVE " + n, 2) for n in live])
    for p in (PIDF, STATE):
        try:
            os.unlink(p)
        except Exception:
            pass


def start(freq):
    stop_all()
    lines = wpa([("P2P_GROUP_ADD freq=%d" % freq, 12)])
    got = [l for l in lines if "P2P-GROUP-STARTED" in l]
    if not got:
        print("Group was not created. Supplicant said:")
        for l in lines:
            print("  " + l)
        return False
    line = got[0]
    iface = line.split("P2P-GROUP-STARTED ")[1].split()[0]
    ssid = line.split('ssid="')[1].split('"')[0]
    pw = line.split('passphrase="')[1].split('"')[0]
    open(STATE, "w").write(iface)
    sh("ip addr add %s.1/24 dev %s" % (NET, iface))
    open("/proc/sys/net/ipv4/ip_forward", "w").write("1")
    sh("iptables -w -t nat -A POSTROUTING -s %s.0/24 -o wlan0 -j MASQUERADE" % NET)
    sh("iptables -w -I INPUT 1 -i %s -j ACCEPT" % iface)
    sh("iptables -w -I FORWARD 1 -i %s -o wlan0 -j ACCEPT" % iface)
    sh("iptables -w -I FORWARD 2 -i wlan0 -o %s -m state --state ESTABLISHED,RELATED -j ACCEPT" % iface)
    sh("ip rule add from %s.0/24 lookup wlan0 pref 1000" % NET)
    sh("ip rule add to %s.0/24 lookup main pref 999" % NET)
    conf = "\n".join([
        "interface=" + iface,
        "bind-interfaces",
        "port=0",
        "user=root",
        "dhcp-range=%s.10,%s.100,255.255.255.0,12h" % (NET, NET),
        "dhcp-option=3,%s.1" % NET,
        "dhcp-option=6,8.8.8.8,1.1.1.1",
        "dhcp-leasefile=/data/local/tmp/dnsmasq-p2p.leases",
        "pid-file=" + PIDF,
        "log-dhcp",
        "log-facility=/data/local/tmp/dnsmasq-p2p.log",
        ""])
    open("/data/local/tmp/dnsmasq-p2p.conf", "w").write(conf)
    err = sh(T + "/bin/dnsmasq -C /data/local/tmp/dnsmasq-p2p.conf")
    if err:
        print("dnsmasq said: " + err)
    print("------------------------------")
    print("Relay running on %d MHz" % freq)
    print("Network name: " + ssid)
    print("Password: " + pw)
    print("------------------------------")
    return True


def auto(force):
    open(WPID, "w").write(str(os.getpid()))

    def bye(a, b):
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, bye)
    last = None
    waiting = False
    print("Relay watcher running. Press Ctrl+C to stop.")
    try:
        while True:
            freq = get_freq()
            if freq is None:
                if last is not None:
                    print("Wi-Fi lost, stopping relay")
                    stop_all()
                    last = None
                if not waiting:
                    print("Waiting for Wi-Fi...")
                    waiting = True
            else:
                waiting = False
                target = freq
                if force and freq >= 3000:
                    target = 2437
                gone = not os.path.exists("/sys/class/net/" + readf(STATE)) or not readf(STATE)
                if target != last or gone:
                    print("Source network is on %d MHz" % freq)
                    if freq >= 4900 and not force:
                        print("Note: this is a 5 GHz network. A 2.4 GHz-only laptop will not see the group.")
                    if freq >= 3000 and force:
                        print("Forcing the group onto 2.4 GHz. Expect packet loss.")
                    if start(target):
                        last = target
                    else:
                        last = None
            time.sleep(10)
    except KeyboardInterrupt:
        pass
    finally:
        stop_all()
        print("Relay stopped")


def stop_cmd():
    wp = readf(WPID)
    if wp and wp != str(os.getpid()):
        sh("kill " + wp)
        time.sleep(2)
    stop_all()
    try:
        os.unlink(WPID)
    except Exception:
        pass
    print("Relay stopped")


def install():
    base = ("#!" + T + "/bin/sh\nexec su -c \"LD_LIBRARY_PATH=" + T + "/lib " + T +
            "/bin/python " + H + "/relay.py %s\"\n")
    for name, arg in (("relay", "auto"), ("relay24", "auto24"), ("relay-stop", "stop")):
        p = T + "/bin/" + name
        open(p, "w").write(base % arg)
        os.chmod(p, 0o755)
    print("Installed: relay, relay24, relay-stop")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if a == "install":
        install()
    elif os.geteuid() != 0:
        print("Run this through the relay, relay24 or relay-stop command.")
    elif a == "stop":
        stop_cmd()
    elif a == "auto":
        auto(False)
    elif a == "auto24":
        auto(True)
