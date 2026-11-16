'use strict';
import { readfile, writefile } from 'fs';

// Fixed, driver-owned LED: never accept a sysfs path or a GPIO from a request.
const LED = '/sys/class/leds/e5:white:torch/';

function state() {
 let maximum = trim(readfile(LED + 'max_brightness') ?? '');
 let brightness = trim(readfile(LED + 'brightness') ?? '');
 if (maximum != '1' || (brightness != '0' && brightness != '1'))
  return { ok: false, available: false, on: null, error: 'unavailable' };
 return { ok: true, available: true, on: brightness == '1' };
}

return function(ctx) {
 return {
  'GET /state': state,
  'POST /toggle': function(req) {
   // Toggle the actual current output, not a possibly stale browser value.
   let before = state();
   if (!before.ok) return before;
   let on = !before.on;
   if (writefile(LED + 'brightness', on ? '1\n' : '0\n') == null) {
    let current = state();
    return { ...current, ok: false, error: 'write_failed' };
   }
   let current = state();
   if (!current.ok) return current;
   if (current.on != on)
    return { ...current, ok: false, error: 'readback_failed' };
   return current;
  }
 };
};
