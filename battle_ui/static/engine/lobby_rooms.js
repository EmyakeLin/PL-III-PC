const tabKey = 'pl3-lobby-rooms';
const instanceKey = 'pl3-desktop-instance';
const launch = /^#desktop=([a-f0-9]{32})$/.exec(location.hash);
let storage, key = tabKey, rooms = [];

try {
  storage = sessionStorage;
  if (launch) sessionStorage.setItem(instanceKey, launch[1]);
  const instance = sessionStorage.getItem(instanceKey);
  if (instance) {
    const previous = localStorage.getItem(instanceKey);
    if (launch && previous !== instance) {
      if (previous) localStorage.removeItem(tabKey + '-' + previous);
      localStorage.setItem(instanceKey, instance);
    }
    storage = localStorage;
    key = tabKey + '-' + instance;
  }
} catch { /* Keep the tab or in-memory fallback when storage is unavailable. */ }

export function savedRooms() {
  try {
    const stored = JSON.parse(storage.getItem(key));
    rooms = Array.isArray(stored) ? stored : [];
  } catch { /* Keep invitations in memory if the browser restricts storage. */ }
  return rooms;
}

function writeRooms(nextRooms) {
  rooms = nextRooms;
  try { storage.setItem(key, JSON.stringify(rooms)); }
  catch { storage = null; }
}

export function saveRoom(room) {
  writeRooms([room, ...savedRooms().filter(item => item.id !== room.id)]);
}

export function forgetRoom(id) {
  writeRooms(savedRooms().filter(item => item.id !== id));
}
