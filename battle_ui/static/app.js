/**
 * 《光点计划 III》纯 WebGL 主入口
 *  - Three.js WebGL（动态亮色光场 GLSL Shader + 真实 3D 多面体骰子 + 3D 双面翻牌与牵制弧 + InstancedMesh 碰撞火花）
 *  - Matter.js（固定 60Hz 时间步：真实拼点双骰碰撞与击退 + 可控阻尼手牌惯性 + 护盾磨损碎裂）
 *  - PixiJS v8 WebGL（透明叠加层：正面无畸变清晰卡牌、紧凑角色牌与实体叠牌、四层拼点条与全部交互）
 *  - 原生 RFC 6455 WebSocket 实时双工通信
 */

import * as PIXI from './vendor/pixi.min.mjs';
import { RoomSeatTransport } from './engine/transport.js';
import { bindBattleRecord } from './engine/battle_record.js';
import { TabletopAudio } from './engine/audio.js';
import { TabletopPhysics } from './engine/physics.js';
import { ThreeWorld } from './engine/three_world.js';
import { GameDirector } from './engine/game_director.js';
import { makeSealButton } from './engine/table_overlays.js';
import { FONT_NUM, FONT_UI, INK } from './engine/design_system.js';
import { savedRooms, saveRoom } from './engine/lobby_rooms.js';

async function boot() {
  const threeCanvas = document.getElementById('three-canvas');
  const pixiCanvas = document.getElementById('pixi-canvas');
  if (!threeCanvas || !pixiCanvas) throw new Error('缺少 WebGL 画布节点。');

  if (!window.Matter) {
    await new Promise((resolve) => {
      const check = () => (window.Matter ? resolve() : setTimeout(check, 16));
      check();
    });
  }

  const threeWorld = new ThreeWorld(threeCanvas);
  const physics = new TabletopPhysics(window.innerWidth, window.innerHeight);

  const app = new PIXI.Application();
  await app.init({
    canvas: pixiCanvas,
    preference: 'webgl',
    antialias: true,
    backgroundAlpha: 0,
    resolution: Math.min(window.devicePixelRatio || 1, 2),
    autoDensity: true,
    resizeTo: window,
  });

  const audio = new TabletopAudio();
  const table = location.pathname.match(/^(.*)\/(canvas|table)\/(?:index\.html)?$/);
  const baseUrl = table?.[1] || '';
  const token = new URLSearchParams(location.hash.slice(1)).get('token');
  const transport = new RoomSeatTransport(token, baseUrl);
  const openBattleRecord = bindBattleRecord(transport);
  const hosted = baseUrl.startsWith('/rooms/');
  const returnToLobby = () => {
    if (hosted) {
      const id = baseUrl.split('/').pop();
      if (token && director.state && !savedRooms().some(r => r.id === id)) {
        saveRoom({
          id,
          code: director.state.room_code || '',
          label: roomName ? roomName.text : '对局房间',
          play_url: location.pathname + location.hash,
        });
      }
    }
    transport.close();
    location.assign('/lobby/');
  };

  const director = new GameDirector(app, physics, threeWorld, audio, transport, openBattleRecord, returnToLobby);
  const footerHeight = hosted ? 38 : 0;
  let footer, footerPaper, roomName, copyCodeBtn;
  let currentRoomCode = '';
  if (hosted) {
    footer = new PIXI.Container();
    footerPaper = new PIXI.Graphics();
    roomName = new PIXI.Text({ text: '', style: { fontFamily: FONT_UI, fontSize: 13.5, fontWeight: '700', fill: INK.secondary } });
    roomName.position.set(126, 9);
    const leave = makeSealButton('返回大厅', {
      width: 98, height: 27, fontSize: 13, accent: INK.goldDeep, onClick: returnToLobby,
    });
    leave.position.set(16, 5);
    copyCodeBtn = makeSealButton('复制房间码', {
      width: 118, height: 27, fontSize: 12, accent: 0x1a825e,
      onClick: async () => {
        if (!currentRoomCode) return;
        try {
          await navigator.clipboard.writeText(currentRoomCode);
          director.showToast(`已复制房间码 ${currentRoomCode}，发给朋友即可在大厅输入加入！`, 0x1a825e, 2.4);
        } catch {
          director.showToast(`本房房间码：${currentRoomCode}`, INK.gold, 3.2);
        }
      },
    });
    copyCodeBtn.visible = false;
    footer.addChild(footerPaper, roomName, leave, copyCodeBtn);
    app.stage.addChild(footer);
  }

  const handleResize = () => {
    const w = window.innerWidth;
    const h = window.innerHeight - footerHeight;
    threeWorld.resize(w, h);
    physics.resize(w, h);
    app.renderer.resize(w, window.innerHeight);
    director.resize(w, h);
    if (hosted) {
      threeCanvas.style.height = h + 'px';
      footer.y = h;
      footerPaper.clear().rect(0, 0, w, footerHeight).fill(INK.paperSoft)
        .moveTo(0, 0).lineTo(w, 0).stroke({ color: INK.line, width: 1 });
      if (copyCodeBtn) copyCodeBtn.position.set(w - 134, 5);
    }
  };
  window.addEventListener('resize', handleResize);
  if (hosted) handleResize();

  const applyFrame = (state) => {
    director.applyState(state, { isInitial: !director.state });
    if (roomName) {
      const modeTitle = state.challenge
        || (state.hotseat ? '同屏双人' : state.bot_side ? '单人演练' : state.seat_role === 'spectator' ? '观战席' : '联机房间');
      currentRoomCode = state.room_code || '';
      roomName.text = currentRoomCode ? `${modeTitle}　·　房间码 ${currentRoomCode}` : modeTitle;
      if (copyCodeBtn) {
        copyCodeBtn.visible = Boolean(currentRoomCode && !state.bot_side && !state.hotseat);
      }
    }
  };

  transport.follow(applyFrame, (error) => {
    const message = error?.status === 404 ? '房间已关闭，请返回大厅。'
      : error?.status === 403 ? '邀请凭据无效，请返回大厅重新加入。'
      : error ? (error.message || '房间连接中断，正在自动重连…') : '已重新连接房间。';
    director.showToast(message, error ? 0xcf4932 : 0x1a825e, error ? 3.2 : 1.8);
  });

  let lastTime = performance.now();
  const tick = (now) => {
    const dtSec = Math.min(0.05, Math.max(0.001, (now - lastTime) / 1000));
    lastTime = now;
    physics.step(dtSec);
    director.update(dtSec);
    threeWorld.update(dtSec);
    requestAnimationFrame(tick);
  };
  requestAnimationFrame(tick);

  window.__PL3_ENGINE__ = {
    app,
    physics,
    threeWorld,
    director,
    transport,
    rendererType: app.renderer?.name || 'webgl',
  };
}

boot().catch((err) => {
  const c = document.getElementById('pixi-canvas');
  if (c) {
    const ctx = c.getContext('2d');
    if (ctx) {
      c.width = window.innerWidth;
      c.height = window.innerHeight;
      ctx.fillStyle = '#f6f3eb';
      ctx.fillRect(0, 0, c.width, c.height);
      ctx.fillStyle = '#cf4932';
      ctx.font = 'bold 20px sans-serif';
      ctx.fillText(`WebGL 初始化异常: ${err.message || err}`, 40, 80);
    }
  }
  console.error(err);
});
