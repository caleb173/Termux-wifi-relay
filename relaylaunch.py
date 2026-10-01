import os, sys, subprocess

T = "/data/data/com.termux/files/usr"
H = "/data/data/com.termux/files/home"
NL = chr(10)


def su(arg):
    c = "LD_LIBRARY_PATH=" + T + "/lib " + T + "/bin/python " + H + "/relay.py " + arg
    return subprocess.Popen(["su", "-c", c])


def run(arg):
    p = su(arg)
    try:
        p.wait()
    except KeyboardInterrupt:
        print("Stopping relay...")
        su("stop").wait()
        try:
            p.wait(timeout=15)
        except Exception:
            p.kill()


def install():
    me = H + "/relaylaunch.py"
    for name, arg in (("relay", "auto"), ("relay24", "auto24"), ("relay-stop", "stop")):
        path = T + "/bin/" + name
        body = "#!" + T + "/bin/sh" + NL + "exec " + T + "/bin/python " + me + " " + arg + NL
        open(path, "w").write(body)
        os.chmod(path, 0o755)
    print("Installed: relay, relay24, relay-stop")


if __name__ == "__main__":
    a = sys.argv[1] if len(sys.argv) > 1 else "auto"
    if a == "install":
        install()
    elif a == "stop":
        su("stop").wait()
    else:
        run(a)
