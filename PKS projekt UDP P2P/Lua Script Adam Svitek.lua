
--LUA SCRIPT
my_proto = Proto("myproto", "My Custom Protocol")


local f = my_proto.fields

f.message_type = ProtoField.uint8("myproto.message_type", "Message Type", base.DEC)
f.message_id = ProtoField.uint8("myproto.message_id", "Message ID", base.DEC)
f.fragment_number = ProtoField.uint16("myproto.fragment_number", "Fragment Number", base.DEC)
f.total_fragments = ProtoField.uint16("myproto.total_fragments", "Total Fragments", base.DEC)
f.length = ProtoField.uint16("myproto.length", "Length", base.DEC)
f.checksum = ProtoField.uint16("myproto.checksum", "Checksum", base.HEX)
f.future_flag = ProtoField.uint16("myproto.future_flag", "Future Flag", base.HEX)
f.payload = ProtoField.bytes("myproto.payload", "Payload")

my_proto.prefs["udp_port"] = Pref.uint("UDP Port", 12345, "UDP Port to decode as My Custom Protocol")


function my_proto.dissector(buffer, pinfo, tree)

    if buffer:len() < 12 then return end

    
    pinfo.cols.protocol = "MyProto"

    local subtree = tree:add(my_proto, buffer(), "My Custom Protocol Data")

    local offset = 0
    local message_type = buffer(offset, 1):uint()
    subtree:add(f.message_type, buffer(offset, 1))
    offset = offset + 1

    local message_id = buffer(offset, 1):uint()
    subtree:add(f.message_id, buffer(offset, 1))
    offset = offset + 1

    local fragment_number = buffer(offset, 2):uint()
    subtree:add(f.fragment_number, buffer(offset, 2))
    offset = offset + 2

    local total_fragments = buffer(offset, 2):uint()
    subtree:add(f.total_fragments, buffer(offset, 2))
    offset = offset + 2

    local length = buffer(offset, 2):uint()
    subtree:add(f.length, buffer(offset, 2))
    offset = offset + 2

    local checksum = buffer(offset, 2):uint()
    subtree:add(f.checksum, buffer(offset, 2))
    offset = offset + 2

    local future_flag = buffer(offset, 2):uint()
    subtree:add(f.future_flag, buffer(offset, 2))
    offset = offset + 2

   
    local payload_length = buffer:len() - offset
    if payload_length > 0 then
        local payload_buffer = buffer(offset, payload_length)
        subtree:add(f.payload, payload_buffer)
    end

    if message_type == 1 or message_type == 2 or message_type == 3 then
        -- Handshake messages
        subtree:set_text("Handshake Message")
        pinfo.cols.info = "Handshake Message"
        pinfo.cols.protocol:append(" [HS]")
    elseif message_type == 4 then
        -- Data messages
        subtree:set_text("Data Message")
        pinfo.cols.info = "Data Message"
        pinfo.cols.protocol:append(" [DATA]")
    elseif message_type == 5 or message_type == 6 then
        -- File metadata and file data messages
        subtree:set_text("File Transfer Message")
        pinfo.cols.info = "File Transfer Message"
        pinfo.cols.protocol:append(" [FILE]")
    elseif message_type == 7 or message_type == 8 then
        -- Heartbeat messages
        subtree:set_text("Heartbeat Message")
        pinfo.cols.info = "Heartbeat Message"
        pinfo.cols.protocol:append(" [HB]")
    elseif message_type == 9 then
        --ACK-DATA
        subtree:set_text("data received message")
         pinfo.cols.info = "Received data"
         pinfo.cols.protocol:append(" [AD]")
    else
        -- Unknown or other messages
        subtree:set_text("Unknown Message")
        pinfo.cols.info = "Unknown Message"
    end
end


local udp_port = my_proto.prefs["udp_port"]


function my_proto.init()
    local udp_dissector_table = DissectorTable.get("udp.port")
    udp_dissector_table:add(udp_port, my_proto)
end

function my_proto.prefs_changed()
    my_proto.init()
end
