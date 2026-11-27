/**
 * Declarative FX DSL Interpreter & Custom FX Script Host for 《光点计划 III》.
 *
 * Bridges backend-compiled `character_fx` manifests (from `_packs/fx/<char_id>.json`
 * or inline `fx` / `fx_prompt` fields) and optional `/fx_scripts/<name>.js` modules
 * directly onto:
 *  - Three.js 3D VFX (`three_world.js`)
 *  - PR #1 Skeletal Bone World Anchors (`actor.getBoneWorldPos('bone_weapon')`)
 *  - Matter.js Physics Shards (`physics.js`)
 *  - Procedural WebAudio Synth (`audio.js`)
 *  - Camera Shake & Floating Callout Banners (`game_director.js`)
 */

const SCRIPT_CACHE = new Map();

function parseHexToInt(raw, fallback = 0xd99426) {
  if (typeof raw === 'number' && Number.isFinite(raw)) return raw & 0xffffff;
  if (typeof raw === 'string') {
    const clean = raw.trim().replace(/^#|^0x/i, '');
    if (/^[0-9a-f]{6}$/i.test(clean)) return parseInt(clean, 16);
  }
  return fallback;
}

export class FxDirector {
  constructor({
    three,
    physics,
    audio,
    getActorNode,
    getActorPos,
    getMotion,
    getMatchNumber = () => undefined,
    deferFx = setTimeout,
    getClashCenter,
    triggerShake,
    spawnFloater,
    showBanner,
  }) {
    this.three = three;
    this.physics = physics;
    this.audio = audio;
    this.getActorNode = getActorNode;
    this.getActorPos = getActorPos;
    this.getMotion = getMotion;
    this.getMatchNumber = getMatchNumber;
    this.deferFx = deferFx;
    this.getClashCenter = getClashCenter;
    this.triggerShake = triggerShake;
    this.spawnFloater = spawnFloater;
    this.showBanner = showBanner;

    this.manifests = {};
    this.scriptUrls = {};
  }

  sync(characterFx, fxScripts) {
    this.manifests = characterFx && typeof characterFx === 'object' ? characterFx : {};
    this.scriptUrls = fxScripts && typeof fxScripts === 'object' ? fxScripts : {};
  }

  /**
   * Resolve a semantic anchor (`attacker.bone_weapon`, `defender.center`, `clash.center`, etc.)
   * into exact stage pixel coordinates using PR #1's skeletal bone world positions.
   */
  resolveAnchor(anchorName, ctx) {
    const fallbackAttacker = ctx.attackerId ? this.getActorPos(ctx.attackerId, ctx.attackerSide) : this.getClashCenter();
    const fallbackDefender = ctx.defenderId ? this.getActorPos(ctx.defenderId, ctx.defenderSide) : this.getClashCenter();
    if (!anchorName) return fallbackDefender;

    if (anchorName === 'clash.center') {
      return this.getClashCenter();
    }

    const [role, part = 'center'] = String(anchorName).split('.');
    const charId = role === 'defender' ? ctx.defenderId : ctx.attackerId;
    const side = role === 'defender' ? ctx.defenderSide : ctx.attackerSide;
    if (!charId) return role === 'defender' ? fallbackDefender : fallbackAttacker;

    if (part.startsWith('bone_')) {
      const node = this.getActorNode(charId, side);
      if (node?.actor && typeof node.actor.getBoneWorldPos === 'function') {
        const bp = node.actor.getBoneWorldPos(part);
        if (bp && Number.isFinite(bp.x) && Number.isFinite(bp.y)) {
          // Convert actor-container world pos using node.cx / node.cy offset for scrollable wings
          const dx = bp.x - node.actor.x;
          const dy = bp.y - node.actor.y;
          return { x: node.cx + dx, y: node.cy + dy };
        }
      }
    }
    return this.getActorPos(charId, side);
  }

  /**
   * Lookup the most specific FX recipe for a combat strike event:
   *  1. skills[cardId].dice[dieNumber] or skills[cardName].dice[dieNumber]
   *  2. skills[cardId].on_strike / skills[cardName].on_strike
   *  3. defaults[dieType]
   *  4. defaults.strike
   */
  resolveStrikeRecipe(ev) {
    const m = this.manifests[ev.attacker_id];
    if (!m) return null;
    const skills = m.skills || {};
    const skillEntry = (ev.card_id && skills[ev.card_id]) || (ev.card_name && skills[ev.card_name]) || null;
    if (skillEntry) {
      if (ev.die_number != null && skillEntry.dice && skillEntry.dice[String(ev.die_number)]) {
        return skillEntry.dice[String(ev.die_number)];
      }
      if (skillEntry.on_strike) return skillEntry.on_strike;
      if (skillEntry.on_hit) return skillEntry.on_hit;
    }
    const defs = m.defaults || {};
    if (ev.die_type && defs[ev.die_type]) return defs[ev.die_type];
    if (defs.strike) return defs.strike;
    return null;
  }

  resolvePassiveRecipe(ev) {
    const m = this.manifests[ev.character_id];
    if (!m) return null;
    if (m.passives && ev.passive_name && m.passives[ev.passive_name]) {
      return m.passives[ev.passive_name];
    }
    return m.defaults?.passive || null;
  }

  resolveStatusRecipe(ev) {
    const m = this.manifests[ev.character_id];
    if (!m || !m.defaults || !ev.status) return null;
    return m.defaults[`status:${ev.status}`] || null;
  }

  _skillEntry(charId, cardId, cardName) {
    const m = charId ? this.manifests[charId] : null;
    if (!m || !m.skills) return null;
    return (cardId && m.skills[cardId]) || (cardName && m.skills[cardName]) || null;
  }

  resolveSkillUseRecipe(ev) {
    const m = ev?.character_id ? this.manifests[ev.character_id] : null;
    if (!m) return null;
    const sk = this._skillEntry(ev.character_id, ev.card_id, ev.card_name);
    if (sk) {
      if (ev.active_form && sk.forms && sk.forms[ev.active_form]) return sk.forms[ev.active_form];
      if (ev.active_form && sk.on_form_change) return sk.on_form_change;
      if (sk.on_skill_use) return sk.on_skill_use;
      if (sk.on_cast) return sk.on_cast;
    }
    if (ev.active_form && m.defaults?.on_form_change) return m.defaults.on_form_change;
    return m.defaults?.on_skill_use || null;
  }

  resolveClashWinRecipe(sideEntry) {
    if (!sideEntry?.character_id) return null;
    const m = this.manifests[sideEntry.character_id];
    if (!m) return null;
    const skills = m.skills || {};
    const skillEntry = (sideEntry.card_id && skills[sideEntry.card_id]) || null;
    if (skillEntry?.on_clash_win) return skillEntry.on_clash_win;
    return null;
  }

  /**
   * Estimate exact first-contact `impactMs` and total `durationMs` from a declarative FX recipe
   * so defender recoil, hitFlash, and HP/Lightcore bar drops align with projectile/blade arrival!
   */
  estimateRecipeTiming(recipe) {
    if (!recipe || typeof recipe !== 'object') return { impactMs: 90, durationMs: 220 };
    const atoms = Array.isArray(recipe.vfx) ? recipe.vfx : [];
    let firstContact = Infinity;
    let maxEnd = 180;
    for (const atom of atoms) {
      const delay = Math.max(0, Number(atom.delay_ms) || 0);
      const count = Math.max(1, Math.min(6, atom.primitive === 'sparks' || atom.primitive === 'shards' ? 1 : (atom.count || 1)));
      const stagger = Math.max(0, Number(atom.stagger_ms) || 90);
      let contactOffset = 75;
      let atomDur = Number(atom.duration_ms) || 320;
      if (atom.primitive === 'pierce_lance') {
        contactOffset = 135;
        atomDur = 360;
      } else if (atom.primitive === 'beam') {
        const dur = Math.max(120, Math.min(1400, Number(atom.duration_ms) || 440));
        contactOffset = Math.round(dur * 0.78);
        atomDur = dur;
      } else if (atom.primitive === 'slash_arc') {
        contactOffset = 85;
        atomDur = 400;
      } else if (atom.primitive === 'ground_shockwave') {
        contactOffset = 70;
        atomDur = 380;
      }
      if (atom.to !== 'attacker.center' && atom.primitive !== 'shield_dome') {
        firstContact = Math.min(firstContact, delay + contactOffset);
      }
      maxEnd = Math.max(maxEnd, delay + (count - 1) * stagger + atomDur);
    }
    const impactMs = Number.isFinite(firstContact) ? Math.max(35, Math.min(650, firstContact)) : 90;
    return { impactMs, durationMs: Math.max(impactMs + 80, maxEnd) };
  }

  /**
   * Execute a validated FX recipe (returns `{ ran: true, impactMs, durationMs }` if custom FX ran, else `false`).
   */
  playRecipe(recipe, ctx, { silent = false } = {}) {
    if (!recipe || typeof recipe !== 'object') return false;
    const hasCustom = Boolean(
      (Array.isArray(recipe.vfx) && recipe.vfx.length)
      || recipe.sfx
      || recipe.script
      || recipe.camera
      || recipe.motion
    );
    if (!hasCustom) return false;

    const timing = this.estimateRecipeTiming(recipe);
    const motion = recipe.motion || {};
    const separateDefender = Boolean(ctx.defenderId && ctx.defenderId !== ctx.attackerId && timing.impactMs > 20);

    // 1a. Attacker windup motions fire immediately at t = 0
    if (ctx.attackerId) {
      const am = this.getMotion(ctx.attackerId, ctx.attackerSide);
      if (motion.lunge) am.lunge = Math.max(am.lunge, motion.lunge);
      if (motion.evade) am.evade = Math.max(am.evade, motion.evade);
      if (motion.healGlow) am.healGlow = Math.max(am.healGlow, motion.healGlow);
      if (motion.passiveFlare) am.passiveFlare = Math.max(am.passiveFlare, motion.passiveFlare);
    }

    // 1b. Defender impact recoil/hitFlash & camera shake fire on arrival (`impactMs`)!
    const applyImpactFeedback = () => {
      if (ctx.defenderId) {
        const dm = this.getMotion(ctx.defenderId, ctx.defenderSide);
        if (motion.recoil) dm.recoil = Math.max(dm.recoil, motion.recoil);
        if (motion.hitFlash) dm.hitFlash = Math.max(dm.hitFlash, motion.hitFlash);
      }
      if (recipe.camera?.shake > 0) {
        const durSec = Math.max(0.06, Math.min(0.7, (recipe.camera.duration_ms || 220) / 1000));
        this.triggerShake?.(recipe.camera.shake, durSec);
      }
    };
    if (separateDefender) {
      this.deferFx(applyImpactFeedback, timing.impactMs);
    } else {
      applyImpactFeedback();
    }

    // 2. Audio (preset or procedural WebAudio synth)
    if (!silent && recipe.sfx) {
      const pan = ctx.attackerSide === 1 ? -0.24 : ctx.attackerSide === 2 ? 0.24 : 0;
      this.audio?.playSynthRecipe(recipe.sfx, pan);
    }

    // 3. Visual Atoms
    if (Array.isArray(recipe.vfx)) {
      for (const atom of recipe.vfx) {
        this._dispatchAtom(atom, ctx);
      }
    }

    // 4. Optional Custom JS FX Script Plugin (`/fx_scripts/<name>.js`)
    if (recipe.script?.url) {
      this._invokeCustomScript(recipe.script, ctx);
    }

    return { ran: true, ...timing };
  }

  _dispatchAtom(atom, ctx) {
    const count = Math.max(1, Math.min(6, atom.primitive === 'sparks' || atom.primitive === 'shards' ? 1 : (atom.count || 1)));
    const baseDelay = Math.max(0, atom.delay_ms || 0);
    const stagger = Math.max(0, atom.stagger_ms || 90);

    for (let i = 0; i < count; i++) {
      const wait = baseDelay + i * stagger;
      const exec = () => this._runSingleAtom(atom, ctx, i);
      if (wait <= 0) exec();
      else this.deferFx(exec, wait);
    }
  }

  _runSingleAtom(atom, ctx, iteration = 0) {
    const colorInt = parseHexToInt(atom.color, ctx.defaultColor || 0xd99426);
    const fromPt = this.resolveAnchor(atom.from || 'attacker.bone_weapon', ctx);
    const toPt = this.resolveAnchor(atom.to || 'defender.center', ctx);
    // Subtle multi-hit vertical offset so consecutive slashes/lances fan cleanly instead of overlapping
    const fanOffsetY = iteration > 0 ? ((iteration % 2 === 0 ? -1 : 1) * Math.min(24, iteration * 11)) : 0;

    switch (atom.primitive) {
      case 'slash_arc':
        this.three?.spawnSlashArc({
          fromX: fromPt.x,
          fromY: fromPt.y + fanOffsetY * 0.5,
          toX: toPt.x,
          toY: toPt.y + fanOffsetY,
          colorHex: colorInt,
        });
        break;
      case 'sprite_vfx':
        if (atom.url) {
          this.three?.spawnSpriteVfx?.({
            fromX: atom.from ? fromPt.x : toPt.x,
            fromY: atom.from ? fromPt.y : toPt.y,
            toX: toPt.x,
            toY: toPt.y,
            url: atom.url,
            colorHex: colorInt,
            scale: atom.scale || 1.0,
            spin: atom.spin || 0,
            duration: Math.max(0.14, Math.min(1.4, (atom.duration_ms || 480) / 1000)),
          });
        }
        break;
      case 'pierce_lance':
        this.three?.spawnPierceLance({
          fromX: fromPt.x,
          fromY: fromPt.y + fanOffsetY * 0.5,
          toX: toPt.x,
          toY: toPt.y + fanOffsetY,
          colorHex: colorInt,
        });
        break;
      case 'ground_shockwave':
        this.three?.spawnBluntImpact({ toX: toPt.x, toY: toPt.y, colorHex: colorInt });
        this.three?.emitShockwave(toPt.x, toPt.y, colorInt);
        break;
      case 'beam':
        this.three?.spawnEnergyBeam({
          fromX: fromPt.x,
          fromY: fromPt.y + fanOffsetY * 0.4,
          toX: toPt.x,
          toY: toPt.y + fanOffsetY * 0.6,
          colorHex: colorInt,
          duration: Math.max(0.12, Math.min(1.4, (atom.duration_ms || 440) / 1000)),
        });
        break;
      case 'shockwave_ring':
        this.three?.emitShockwave(
          toPt.x,
          toPt.y,
          colorInt,
          Math.max(0.25, Math.min(1.4, (atom.duration_ms || 720) / 1000)),
        );
        break;
      case 'ripple':
        this.three?.triggerRipple(toPt.x, toPt.y, colorInt);
        break;
      case 'sparks':
        this.three?.spawnImpactBurst(
          toPt.x,
          toPt.y,
          colorInt,
          Math.max(4, Math.min(64, atom.count || 24)),
          Boolean(atom.heavy),
        );
        break;
      case 'shield_dome':
        this.three?.spawnShieldDomePulse({
          x: toPt.x,
          y: toPt.y,
          radius: Math.max(24, Math.min(140, atom.radius || 58)),
          colorHex: colorInt,
        });
        break;
      case 'block_barrier':
        this.three?.spawnBlockBarrier({ x: toPt.x, y: toPt.y, colorHex: colorInt });
        break;
      case 'shards':
        this.physics?.spawnShieldShards(
          toPt.x,
          toPt.y,
          colorInt,
          Math.max(3, Math.min(28, atom.count || 10)),
          Boolean(atom.heavy),
        );
        break;
      case 'banner':
        if (atom.text) {
          this.spawnFloater?.(toPt.x, toPt.y - 44, atom.text, colorInt, 15, atom.kind || 'clash');
        }
        break;
      default:
        break;
    }
  }

  async _invokeCustomScript(scriptRef, ctx) {
    const matchNumber = this.getMatchNumber();
    try {
      const url = scriptRef.url;
      let modPromise = SCRIPT_CACHE.get(url);
      if (!modPromise) {
        modPromise = import(url);
        SCRIPT_CACHE.set(url, modPromise);
      }
      const mod = await modPromise;
      if (matchNumber !== this.getMatchNumber()) return;
      const fn = mod?.[scriptRef.export] || mod?.default;
      if (typeof fn !== 'function') return;

      // Controlled sandboxed API passed to custom FX scripts
      const api = {
        three: this.three,
        physics: this.physics,
        audio: this.audio,
        defer: this.deferFx,
        resolveAnchor: (name) => this.resolveAnchor(name, ctx),
        shake: (power, durSec = 0.25) => this.triggerShake?.(Math.min(18, power), Math.min(0.7, durSec)),
        floater: (x, y, text, colorHex, kind = 'clash') =>
          this.spawnFloater?.(x, y, String(text || '').slice(0, 28), parseHexToInt(colorHex), 15, kind),
        banner: (text, colorHex, dur = 1.4) =>
          this.showBanner?.(String(text || '').slice(0, 36), parseHexToInt(colorHex), Math.min(2.4, dur)),
        motion: (charId) => this.getMotion(charId),
      };
      fn(api, ctx);
    } catch (_) {
      // Custom script errors must never interrupt core battle playback
    }
  }
}
