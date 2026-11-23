import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

const source = readFileSync(new URL('../battle_ui/static/engine/lobby_rooms.js', import.meta.url), 'utf8');
function storage() {
  const values = new Map();
  return { getItem: k => values.get(k) ?? null, setItem: (k, v) => values.set(k, v),
    removeItem: k => values.delete(k) };
}
const localStorage = storage();
function openTab(hash = '', sessionStorage = storage()) {
  const context = vm.createContext({ location: {hash}, localStorage, sessionStorage });
  vm.runInContext(source.replaceAll('export function', 'function'), context);
  return context;
}
const launch = '#desktop=' + 'a'.repeat(32);
const tab = openTab(launch);
tab.saveRoom({ id: 'match', play_url: '/rooms/match/#token=private' });
assert.equal(openTab(launch).savedRooms()[0].play_url, '/rooms/match/#token=private');
assert.equal(openTab('', tab.sessionStorage).savedRooms()[0].id, 'match');
assert.equal(openTab().savedRooms().length, 0);
openTab(launch).forgetRoom('match');
assert.equal(tab.savedRooms().length, 0);
tab.saveRoom({ id: 'old' });
assert.equal(openTab('#desktop=' + 'b'.repeat(32)).savedRooms().length, 0);
