import * as fs from 'fs';
import { run_guard } from '/guard/events.uc';

let reads = 0;
let ticks = 0;
run_guard({}, () => {
    fs.writefile('/fixtures/checkpoint-reads', '' + (++reads));
    return { present: 1, capacity: 50, voltage: 3800000, status: 'Charging' };
}, () => die('unexpected poweroff\n'), {
    interval_ms: 100, // Fake checkpoint; no block access in this test.
    tick: () => fs.writefile('/fixtures/checkpoint-ticks', '' + (++ticks)),
});
fs.writefile('/fixtures/checkpoint-stopped', '' + ticks);
