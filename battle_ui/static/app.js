/**
 * 《光点计划 III》纯 WebGL 主入口
 * 对战控件绘制于 WebGL，战报复制使用原生文本框：
 *  - Three.js WebGL（动态亮色光场 GLSL Shader + 真实 3D 多面体骰子 + 3D 双面翻牌与牵制弧 + InstancedMesh 碰撞火花）
 *  - Matter.js（固定 60Hz 时间步：真实拼点双骰碰撞与击退 + 可控阻尼手牌惯性 + 护盾磨损碎裂）
 *  - PixiJS v8 WebGL（透明叠加层：正面无畸变清晰卡牌、紧凑角色牌与实体叠牌、四层拼点条与全部交互）
 */

import * as PIXI from './vendor/pixi.min.mjs';
import { LocalBattleTransport, RoomSeatTransport } from './engine/transport.js';
import { bindBattleRecord } from './engine/battle_record.js';
import { TabletopAudio } from './engine/audio.js';
import { TabletopPhysics } from './engine/physics.js';
import { ThreeWorld } from './engine/three_world.js';
import { GameDirector } from './engine/game_director.js';
import { makeSealButton } from './engine/table_overlays.js';
import { FONT_UI, INK } from './engine/design_system.js';
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

  // 1. Three.js WebGL bright light-field shader + 3D dice + 3D card flips
  const threeWorld = new ThreeWorld(threeCanvas);

  // 2. Fixed-60Hz Matter.js physics engine
  const physics = new TabletopPhysics(window.innerWidth, window.innerHeight);

  // 3. PixiJS v8 WebGL transparent crisp 2D layer
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
  const isRoom = table?.[2] === 'canvas';
  const token = new URLSearchParams(location.hash.slice(1)).get('token');
  const transport = isRoom ? new RoomSeatTransport(token, baseUrl) : new LocalBattleTransport(baseUrl, token);
  const openBattleRecord = bindBattleRecord(transport);
  const hosted = baseUrl.startsWith('/rooms/');
  const returnToLobby = hosted ? () => {
    const id = baseUrl.split('/').pop();
    if (token && director.state && !savedRooms().some(r => r.id === id)) {
      saveRoom({ id, label: roomName.text, play_url: location.pathname + location.hash });
    }
    location.assign('/lobby/');
  } : null;
  const director = new GameDirector(app, physics, threeWorld, audio, transport, openBattleRecord, returnToLobby);
  const footerHeight = hosted ? 38 : 0;
  let footer, footerPaper, roomName;
  if (hosted) {
    footer = new PIXI.Container();
    footerPaper = new PIXI.Graphics();
    roomName = new PIXI.Text({ text: '', style: { fontFamily: FONT_UI, fontSize: 14, fill: INK.secondary } });
    roomName.position.set(128, 9);
    const leave = makeSealButton('返回大厅', { width: 98, height: 27, fontSize: 13, accent: INK.goldDeep,
      onClick: returnToLobby });
    leave.position.set(16, 4);
    footer.addChild(footerPaper, roomName, leave);
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
    }
  };
  window.addEventListener('resize', handleResize);
  if (hosted) handleResize();

  const applyFrame = state => {
    director.applyState(state, { isInitial: !director.state });
    if (roomName) roomName.text = state.challenge || (state.ai_side || state.bot_side ? '单人对战' : '热座对战');
  };

  if (isRoom) {
    transport.follow(applyFrame, error => {
      const message = error?.status === 404 ? '房间已关闭，请返回大厅。'
        : error?.status === 403 ? '邀请已失效，请用本局的私人邀请。'
        : error ? '房间连接中断，正在重连。' : '已重新连接房间。';
      director.showToast(message, error ? 0xcf4932 : 0x1a825e, 5);
    });
  } else {
    try {
      const initial = await transport.fetchState();
      applyFrame(initial);
    } catch (err) {
      director.showToast(`连接战局失败：${err.message || err}`, 0xcf4932, 6);
    }
  }

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
