# Line protocol for bf16_host.py: "<bits> <hex>" shifts one DR scan, "<hex>" is the reply.
# quartus_stp buffers stdout until it exits, so the conversation uses a loopback socket.
set hardware [lindex [get_hardware_names] 0]
set device ""
foreach name [get_device_names -hardware_name $hardware] {
    if {[string match "*5CSE*" $name]} { set device $name }
}
if {$device eq ""} { error "no Cyclone V on $hardware" }
open_device -hardware_name $hardware -device_name $device
device_lock -timeout 10000
device_virtual_ir_shift -instance_index 0 -ir_value 1 -no_captured_ir_value
set channel [socket 127.0.0.1 $env(BF16_HOST_PORT)]
fconfigure $channel -buffering line -translation lf
puts $channel "READY"
while {[gets $channel line] >= 0} {
    lassign $line bits hex
    puts $channel [device_virtual_dr_shift -instance_index 0 -length $bits -dr_value $hex -value_in_hex]
}
close $channel
device_unlock
close_device
