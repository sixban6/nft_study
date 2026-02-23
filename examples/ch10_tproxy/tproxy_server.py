import socket

# IP_TRANSPARENT flag is 19 on Linux
IP_TRANSPARENT = 19

s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
# Required to bind to non-local IP addresses or to receive TPROXY traffic
s.setsockopt(socket.IPPROTO_IP, IP_TRANSPARENT, 1)

s.bind(('0.0.0.0', 12345))
s.listen(5)
print("TPROXY Debug Server listening on port 12345...", flush=True)

while True:
    try:
        conn, addr = s.accept()
        # In TPROXY, the local socket address is the original destination!
        dest_ip, dest_port = conn.getsockname()
        
        # Consume the HTTP request to avoid TCP RST
        data = conn.recv(1024)
        
        msg = f"HTTP/1.1 200 OK\r\n\r\nIntercepted connection from {addr[0]}:{addr[1]} destined for {dest_ip}:{dest_port}\n"
        print(f"Intercepted: {addr[0]}:{addr[1]} -> {dest_ip}:{dest_port}", flush=True)
        conn.sendall(msg.encode('utf-8'))
        conn.close()
    except Exception as e:
        print(f"Error: {e}")
