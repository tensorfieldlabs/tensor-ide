import socket
import threading

def handle_client(client_socket):
    request = client_socket.recv(4096)
    print("--- REQUEST ---")
    print(request.decode('utf-8', errors='ignore'))
    print("---------------")
    client_socket.close()

server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind(('127.0.0.1', 8888))
server.listen(5)
print("Proxy listening on port 8888")

while True:
    client, addr = server.accept()
    threading.Thread(target=handle_client, args=(client,)).start()
