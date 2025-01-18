#pouzite kniznice
import socket
import struct
import threading
import time
import os
import queue

# STATIC veci pri praci s kodom
HANDSHAKE_DONE = threading.Event()
CONNECTED = threading.Event()
CONNECTED.set()
missed_heartbeat = 0 #globalne nastaveny pocet sprav beat na ktore sa nedostala odpoved
MAX_MISSED_BEAST = 3#pocet povelenych heartbeat sprav
heartbeat_interval = 5#ako casto sa ma posielat sprava keep alive
MAX_FRAGMENT_SIZE = 1460#maximalna mozna velkost dat bez hlavicky
ACK_QUEUE = queue.Queue()#kontrola prijatych fragmentov
MESSAGEID = 0 #jedinecne id spravy na sledovanie
save_path = "" #Miesto kde sa budu prijate subory ukladat

#vypocet crc
def crc16(data):
    crc = 0xFFFF
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if (crc & 0x8000):
                crc = ((crc << 1) ^ 0x1021) & 0xFFFF
            else:
                crc = (crc << 1) & 0xFFFF
    return crc


def header(message_type, message_id, fragment_number, total_fragments, length, checksum, future_flag):
    # zabalit do pack
    head = struct.pack(
        '!BBHHHHH',
        message_type,  # 1 byte
        message_id,        # 1 byte
        fragment_number,   # 2 bytes
        total_fragments,   # 2 bytes
        length,            # 2 bytes
        checksum,          # 2 bytes
        future_flag,       #2 bytes pre buduce rozsirenie
    )
    return head

#funkcia  na monitorovanie spojenia keep_alive
def keep_alive_thread(sock, remoteIP, remotePort):
    global missed_heartbeat, heartbeat_interval, MAX_MISSED_BEAST
    while CONNECTED.is_set():#ak pripojene tak sa posiela kazdych 5 sekund sprava beat,
        #  ak  program nedostane odpoved do 3 sprav tak sa spojenie povauje za prerusene
        time.sleep(heartbeat_interval)
        data = b"BEAT"
        head = header(7, 0, 1, 1, len(data), 0, 0)
        fragment = head + data
        sock.sendto(fragment, (remoteIP, remotePort))
        missed_heartbeat += 1
        if missed_heartbeat >= MAX_MISSED_BEAST:
            print("Spojenie bolo prerusene po 3 neprijatych odozvach na spravu heartbeat")
            CONNECTED.clear()
            break
#funkcia pre spustenie funckie na keep_alive aby sa nepustala hned a user mal cas napisat udaje
def start_keep_alive(mySock,remoteIP,remotePort):
    keep_alive = threading.Thread(target=keep_alive_thread, args=(mySock, remoteIP, remotePort))
    keep_alive.start()


#funkcia na poslanie handshake  spravy syn na inicializaciu spojenia
def handshake(sock, remoteIP, remotePort):
    if HANDSHAKE_DONE.is_set(): #ak uz bol tak sa iba vrati a ak nie tak sa posle SYN
        return
    global MESSAGEID
    data = b"SYN"
    print("[HANDSHAKE] Posielam spravu SYN na inicializaciu spojenia")
    head = header(1, MESSAGEID, 1, 1, len(data), 0, 0)
    fragment = head + data
    sock.sendto(fragment, (remoteIP, remotePort))

#posledna funckia pri posielani fragmentou sprav alebo suborov
def fragment_sending(sock, remoteIP, remotePort, message_type, message_id, num_fragments, fragment_size, data):
    for i in range(num_fragments):
        start = i * fragment_size
        end = start + fragment_size
        fragment_number = i + 1
        checksum = crc16(data[start:end])
        head = header(message_type, message_id, fragment_number, num_fragments, len(data[start:end]), checksum, 0)
        fragment = head + (data[start:end])
        #kontrola ci prisla odozva pre kazdy poslany fragment. metoda (Stop and Wait)
        while True:
            sock.sendto(fragment, (remoteIP, remotePort))
            print("poslal som fragment", fragment_number, "/", num_fragments)
            try:

                ACK_accepted = ACK_QUEUE.get(timeout=2)
                #ak pride akceptacna sprava tak sa overuje
                #ak nesedi id tak pokracuje
                if ACK_accepted['message_type'] != 9:
                    continue
                    #ak nesedi cislo fragmentu tak skusa znova
                if ACK_accepted['fragment_number'] != fragment_number:
                    continue
                    #ak bola prijata sprava NACK-DATA cize nesedi crc tak sa fragment posle znova
                if ACK_accepted["message"] == b"NACK-DATA":
                    print("Prijate NACK. Fragment poskodeny,posielam znova")
                    #ak je sprava ACK-DATA tak sa posle dalsi fragment
                elif ACK_accepted["message"] == b"ACK-DATA":
                    print("Prijate ACK pre fragment: ", fragment_number)
                    break

            except queue.Empty:
                print("Nedostal som ACK pre fragment", fragment_number, "posielam znova")
    print("sprava bola odoslana...")

#funkcia na fragmentaciu dat podla velkosti zadanej uzivatelom
def fragmentation(message_len, fragment_size):
    full_fragments = message_len // fragment_size
    remainder_fragment = message_len % fragment_size
    if remainder_fragment >0:
        num_fragments = full_fragments+1
    else:
        num_fragments = full_fragments+2

    return num_fragments

#funkcia send_message ktora sluzi na zistenie aky velky ma byt fragment a
# nasledne spusti funkcie fragmentacia a fragment_sending

def send_message(sock, remoteIP, remotePort, data):
    global MESSAGEID
    fragment_size = int(input("zadajte velkost fragmentu v b(max 1460): "))
    if fragment_size > MAX_FRAGMENT_SIZE:
        fragment_size = MAX_FRAGMENT_SIZE
        print("fragment nemoze byt vacsi ako 1460b. Nastavujem na 1460")

    num_fragments = fragmentation(len(data), fragment_size)
    fragment_sending(sock, remoteIP, remotePort, 4, MESSAGEID, num_fragments, fragment_size, data.encode())

#funkcia send_file otvorenia dat suboru na zadanej adrese a pred prejdenim
# do funkcie fragment_sending posle metadata o subore
def send_file(sock, remoteIP, remotePort, file_path):
    global MESSAGEID
    with open(file_path, "rb") as f:
        data = f.read()
    file_name = os.path.basename(file_path)
    fragment_size = int(input("zadajte velkost fragmentu v b(max 1460): "))
    if fragment_size > MAX_FRAGMENT_SIZE:
        fragment_size = MAX_FRAGMENT_SIZE
        print("fragment nemoze byt vacsi ako 1460b. Nastavujem na 1460")
    num_fragments = fragmentation(len(data), fragment_size)
    metadata = f"{file_name}|{len(data)}|{num_fragments}"
    # poslanie metadat
    head = header(5, MESSAGEID, 1, 1, len(metadata), 0, 0)
    fragment = head + metadata.encode()
    sock.sendto(fragment, (remoteIP, remotePort))
    fragment_sending(sock, remoteIP, remotePort, 6, MESSAGEID, num_fragments, fragment_size, data)

#hlavny thread na posielanie sprav
#na zaciatku uzivatela spyta akuu akciu vykonat:
#1 = handshake 4 = poslanie textovych sprav 5 = poslanie suboru
# tieto akcie sa vykonavaju vo vlastnych funkciach
def send_thread(sock, remoteIP, remotePort):
    global MESSAGEID
    while True:
        message_type = int(input("vyber moznost: "))
        MESSAGEID = (MESSAGEID + 1) % 256
        if message_type == 1:
            if not HANDSHAKE_DONE.is_set():
                handshake(sock, remoteIP, remotePort)
                print("Handshake inicializovany")
                HANDSHAKE_DONE.wait()
        if message_type == 4:
            data = input("zadajte co chcete poslat: ")
            send_message(sock, remoteIP, remotePort, data)
        elif message_type == 5:
            file_path = input("zadajte cestu k suboru: ")
            send_file(sock, remoteIP, remotePort, file_path)

#funkcia ktora sleduje prijate spravy
def receive_thread(sock, remoteIP, remotePort):
    global CONNECTED, missed_heartbeat, MESSAGEID, MAX_FRAGMENT_SIZE,save_path
    message = ""
    file_data = {}
    chyba = True
    chyba_file = True
    while CONNECTED.is_set():
        try:
            msg, addr = sock.recvfrom(MAX_FRAGMENT_SIZE)
        except socket.timeout:
            continue
        header_received = msg[:12]#header
        data_received = msg[12:]#zvysok su data
        message_type, message_id, fragment_number, total_fragments, length, checksum_received, future_flag = struct.unpack(
            '!BBHHHHH', header_received)#rozbalenie headeru
        missed_heartbeat = 0#kedze bola sprava prijata nasstavi sa missed_beats na 0

        if message_type == 1:#prijata rezijina sprava SYN na ktoru sa odpovie SYN-ACK
            print("[HANDSHAKE] prijata sprava SYN.posielam SYN-ACK")
            data = b"SYN-ACK"
            head = header(2, MESSAGEID, 1, 1, len(data), 0, 0)
            sock.sendto(head + data, addr)
        elif message_type == 2:#prijata sprava SYN-ACK na ktoru sa posle odpoved ACK
            print("[HANDSHAKE] prijata sprava SYN-ACK.posielam ACK")
            data = b"ACK"
            head = header(3, MESSAGEID, 1, 1, len(data), 0, 0)
            sock.sendto(head + data, addr)
            start_keep_alive(sock, remoteIP, remotePort)
            HANDSHAKE_DONE.set()#handshake sa povazuje za uspesny na strane prijimatela
        elif message_type == 3:#prijata sprava ACK
            print("[HANDSHAKE] prijata sprava ACK.Spojenie je aktivne")
            start_keep_alive(sock, remoteIP, remotePort)
            HANDSHAKE_DONE.set()#handshake sa povazuje za uspesny na strane prijimatela
        elif message_type == 4:#tento message type prijima fragmenty ktore su obsahom textovej spravy
            print("Received fragment", fragment_number, "/", total_fragments)
            received_checksum = crc16(data_received)
            #simulacia chyby na fragmente cislo 2 kedy sa posle schvalne zly checksum na druhom fragmente
            if chyba == True and fragment_number == 2:
                received_checksum = 1
                chyba = False
            if checksum_received == received_checksum:
                data = b"ACK-DATA"
                message += data_received.decode()
            else:
                data = b"NACK-DATA"
            MESSAGEID = (MESSAGEID + 1) % 256
            head = header(9, MESSAGEID, fragment_number, 1, len(data), 0, 0)
            sock.sendto(head + data, addr)
            if fragment_number == total_fragments:#poskladanie spravy do povodneho textu
                print("Received full message:", message)
                message = ""
        elif message_type == 5:#prijate metadata k suboru ako jeho nazov,velkost, maximalny pocet fragmentov
            metadata = data_received.decode()
            try:
                file_name, file_size, max_fragments = metadata.split("|")
                file_data = {}
                print(f"Receiving file: {file_name} with size {int(file_size)} bytes and {max_fragments} fragments")
            except ValueError:
                print("Invalid metadata")
                continue
        elif message_type == 6:  # prijimanie fragmentov suboru hned po prijati metadat
            print("Received fragment", fragment_number, "/", total_fragments)
            received_checksum = crc16(data_received)
            #simulacia chyby
            if chyba_file == True and fragment_number == 2:
                received_checksum = 1
                chyba_file = False
            if checksum_received == received_checksum:
                data = b"ACK-DATA"
                file_data[fragment_number] = data_received
            else:
                data = b"NACK-DATA"

                chyba_file = False
            MESSAGEID = (MESSAGEID + 1) % 256
            head = header(9, MESSAGEID, fragment_number, 1, len(data), 0, 0)
            sock.sendto(head + data, addr)

            if fragment_number == total_fragments:#ak prisli vsetky fragmenty tak sa pokracuje na vypis
                # a vytovrenie cesty na ulozeneie ak zadana cesta uzivatelom nie je platna
                print("Vsetky fragmenty prijate")
                #vytvorenie cesty
                if not os.path.exists(save_path):
                    os.makedirs(save_path)
                    print(f"Cesta sa nenasla.Vytvaram ju..")
                #informacie o subore
                total_size = sum(len(file_data[i]) for i in range(1, int(max_fragments) + 1))
                fragment_size = len(file_data[1]) if int(max_fragments) > 1 else total_size
                last_fragment_size = len(file_data[int(max_fragments)]) if int(max_fragments) > 1 else total_size
                full_path = os.path.join(save_path, file_name)
                print("Ukladam subor: ",file_name,"\nS velkostou suboru: ",total_size,"\nS velkostou ragmentu:  "
                      ,fragment_size,"\n S velkostou posledneho fragmentu",last_fragment_size,"\nNa adresu: ",full_path)


                with open(full_path, 'wb') as file:
                    for i in range(1, int(max_fragments) + 1):
                        file.write(file_data[i])
        elif message_type == 9:# vyuziva sa pri prijati spravy ACK-DATA na kontrolu stop and wait
            ACK_QUEUE.put({
                "message_type": message_type,
                "message_id": message_id,
                "fragment_number": fragment_number,
                "message": data_received,
            })
            print(data_received)
        elif message_type == 7:#heartbeat sprava na ktoru sa posle fragment ACK beat
            data = b"ACK-BEAT"
            head = header(8, MESSAGEID, fragment_number, 1, len(data), 0, 0)
            fragment = head + data
            sock.sendto(fragment,addr)
        elif message_type == 8:#vynulovanie missed beats
            missed_heartbeat = 0


def main():#hlavna funkcia ktora dovoluje uzivatelovi nastavit vlastne parametre portov a ip adresu druheho klienta
    #taktiez sa pyta na cestu kde by sa mali ukladat subory
    global save_path
    myPort = int(input("Zadajte svoj port: "))
    remoteIP = input("Zadajte ip remote cliena: ")
    remotePort = int(input("Zadajte port cieľa: "))
    save_path = input("Zadajte kde chcete aby sa ukladali prijate subory")
    mySock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    mySock.bind(('', myPort))
    mySock.settimeout(1.0)
    sender_thread = threading.Thread(target=send_thread, args=(mySock, remoteIP, remotePort))
    receiver_thread = threading.Thread(target=receive_thread, args=(mySock, remoteIP, remotePort), daemon=True)
    sender_thread.start()
    receiver_thread.start()

if __name__ == "__main__":    #spustenie programu

    main()
