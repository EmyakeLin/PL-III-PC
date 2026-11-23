const key = 'pl3-lobby-rooms';
let rooms = [];
try {
  const stored = JSON.parse(sessionStorage.getItem(key));
  if (Array.isArray(stored)) rooms = stored;
} catch { /* Private invitations still work when storage is unavailable. */ }

export function savedRooms() { return rooms; }

export function saveRoom(room) {
  rooms = [room, ...rooms.filter(item => item.id !== room.id)];
  writeRooms();
}

export function forgetRoom(id) {
  rooms = rooms.filter(item => item.id !== id);
  writeRooms();
}

function writeRooms() {
  try { sessionStorage.setItem(key, JSON.stringify(rooms)); } catch {}
}
