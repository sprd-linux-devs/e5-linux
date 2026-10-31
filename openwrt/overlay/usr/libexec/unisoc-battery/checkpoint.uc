// Native charged ABI: verified P720S20/P720S11 charged SHA-256
// 3458e12a8a19bc9ff4a422364d39bfdfd439be8b30bbd878ac27a7aa8e2b25a3.
// Original charged writes time(NULL), 8 bytes at 10500, every 15000000 us.
// LK reads that last-alive timestamp as shutdown_rtc_time, then resets it at
// boot. Missing the heartbeat makes a long runtime look like a long shutdown.
import * as fs from 'fs';

export const checkpoint_interval_ms = 15000;
const record_offset = 10496;
const time_offset = 10500;

export function little(bytes, offset, size, signed) {
    let value = 0;
    for (let i = size - 1; i >= 0; i--)
        value = (value << 8) | ord(bytes, offset + i);
    if (signed && size == 4 && value >= 2147483648) value -= 4294967296;
    return value;
};

export function encode_time(value) {
    let bytes = '';
    for (let i = 0; i < 8; i++) {
        bytes += chr(value & 255);
        value >>= 8;
    }
    return bytes;
};

export function native_record_matches(record, bootargs) {
    if (type(record) != 'string' || length(record) != 28 ||
        little(record, 0, 4) != 0x5a5aa5a5 || type(bootargs) != 'string') return false;
    let fields = {};
    for (let token in split(split(bootargs, chr(0))[0], /\s+/)) {
        const m = match(token, /^charge\.(shutdown_rtc_time|charge_cycle|basp|total_mah)=(-?[0-9]+)$/);
        if (!m) continue;
        if (m[1] in fields) return false;
        fields[m[1]] = int(m[2]);
    }
    for (let key in ['shutdown_rtc_time', 'charge_cycle', 'basp', 'total_mah'])
        if (!(key in fields)) return false;
    // Verify the complete vendor record against this boot's actual LK output,
    // not just a model name or a magic word at a guessed block offset.
    if (little(record, 12, 4, true) != fields.charge_cycle ||
        little(record, 16, 4, true) != fields.basp) return false;
    const a = little(record, 20, 4);
    const b = little(record, 24, 4);
    if (fields.total_mah == -1) return a == 0xffffffff && b == 0xffffffff;
    return (a ^ 0x20160726) == fields.total_mah &&
           (b ^ 0x15211517) == fields.total_mah;
};

export function checkpoint_file(file, now, bootargs) {
    if (type(now) != 'int' || now < 1621355101) return 'rtc_invalid';
    if (!file.seek(record_offset)) return 'seek_failed';
    if (!native_record_matches(file.read(28), bootargs)) return 'record_mismatch';
    const value = encode_time(now);
    if (!file.seek(time_offset) || file.write(value) != 8 || !file.flush())
        return 'write_failed';
    if (!file.seek(time_offset) || file.read(8) != value) return 'readback_failed';
    return null;
};

export function start_checkpoint() {
    const path = '/dev/block/by-name/miscdata';
    const bootargs = fs.readfile('/sys/firmware/devicetree/base/chosen/bootargs');
    const st = fs.stat(path);
    if (!st || st.type != 'block' || !bootargs) return null;
    let file = fs.open(path, 'r');
    if (!file) return null;
    const valid = file.seek(record_offset) && native_record_matches(file.read(28), bootargs);
    file.close();
    if (!valid) return null; // Other formats are not written or polled.

    let last_error;
    return {
        interval_ms: checkpoint_interval_ms,
        tick: function() {
            // Match the RTC used by FGU calibration, without changing either
            // the system or hardware clock. No SOC/learning/NV field is written.
            const raw = fs.readfile('/sys/class/rtc/rtc0/since_epoch');
            const now = raw && match(trim(raw), /^[0-9]+$/) ? int(trim(raw)) : null;
            let reason = 'open_failed';
            file = fs.open(path, 'r+');
            if (file) {
                reason = checkpoint_file(file, now, bootargs);
                file.close(); // Flush only this record, like native fclose().
            }
            if (reason && reason != last_error)
                print('battery-checkpoint: ' + reason + '; SOC unchanged\n');
            last_error = reason;
            fs.writefile('/run/e5-battery-checkpoint.json', sprintf('%J\n', {
                ok: !reason, rtc: now, error: reason,
                format: 'unisoc-charged-v1', interval_ms: checkpoint_interval_ms,
            }));
        },
    };
};
