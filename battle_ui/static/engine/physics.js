/**
 * Fixed-timestep (60Hz) Matter.js 2D rigid-body physics engine for 《光点计划 III》.
 * 1) Real Clash Dice Physics: the two actual clashing dice are Matter.js bodies that roll out,
 *    hold briefly so scores are readable, then lunge into each other; collisionStart fires at
 *    the exact physical contact point & frame to drive knockback, sparks, ripples, and audio.
 * 2) Controlled-damping Hand Card Bodies: smooth inertia & clamped subtle banking tilt.
 * 3) Shield Wear (磨损) & Shatter Shards: real tumbling debris bodies.
 */

const FIXED_DT = 1000 / 60;
const CAT_DIE = 0x0001;
const CAT_SHARD = 0x0002;
const CAT_WALL = 0x0004;
const CAT_HAND = 0x0008;

export class TabletopPhysics {
  constructor(width, height) {
    const Matter = window.Matter;
    if (!Matter) throw new Error('Matter.js 未加载。');
    this.Matter = Matter;
    this.width = width;
    this.height = height;
    this.accumulator = 0;

    this.engine = Matter.Engine.create({
      gravity: { x: 0, y: 0, scale: 0 },
    });
    this.world = this.engine.world;

    this.walls = [];
    this.handCards = new Map();
    this.clashGroups = [];
    this.shards = [];
    this.onClashImpact = null; // ({ x, y, speed, group })

    this._rebuildWalls(width, height);
    this._bindCollisionEvents();
  }

  _rebuildWalls(w, h) {
    const { Bodies, Composite } = this.Matter;
    if (this.walls.length) {
      Composite.remove(this.world, this.walls);
      this.walls = [];
    }
    const t = 60;
    const opts = {
      isStatic: true,
      restitution: 0.56,
      friction: 0.05,
      collisionFilter: { category: CAT_WALL, mask: CAT_SHARD },
    };
    this.walls = [
      Bodies.rectangle(w / 2, -t / 2, w + t * 2, t, opts),
      Bodies.rectangle(w / 2, h + t / 2, w + t * 2, t, opts),
      Bodies.rectangle(-t / 2, h / 2, t, h + t * 2, opts),
      Bodies.rectangle(w + t / 2, h / 2, t, h + t * 2, opts),
    ];
    Composite.add(this.world, this.walls);
  }

  _bindCollisionEvents() {
    const { Events, Body, Vector } = this.Matter;
    Events.on(this.engine, 'collisionStart', (event) => {
      for (const pair of event.pairs) {
        const a = pair.bodyA;
        const b = pair.bodyB;
        if (a._clashGroup && a._clashGroup === b._clashGroup && !a._clashGroup.collided) {
          const group = a._clashGroup;
          group.collided = true;
          const support = pair.collision.supports?.[0] || {
            x: (a.position.x + b.position.x) * 0.5,
            y: (a.position.y + b.position.y) * 0.5,
          };
          const relVel = Vector.magnitude(Vector.sub(a.velocity, b.velocity));

          const left = group.leftBody;
          const right = group.rightBody;
          if (group.outcome === 'left_win') {
            Body.setVelocity(left, { x: 2.8, y: 0 });
            Body.setVelocity(right, { x: 16.5, y: -3.2 });
            Body.setAngularVelocity(right, 0.34);
          } else if (group.outcome === 'right_win') {
            Body.setVelocity(right, { x: -2.8, y: 0 });
            Body.setVelocity(left, { x: -16.5, y: -3.2 });
            Body.setAngularVelocity(left, -0.34);
          } else {
            Body.setVelocity(left, { x: -9.5, y: -1.4 });
            Body.setVelocity(right, { x: 9.5, y: -1.4 });
            Body.setAngularVelocity(left, -0.18);
            Body.setAngularVelocity(right, 0.18);
          }

          const impact = { x: support.x, y: support.y, speed: relVel, group };
          if (group.onImpact) {
            const cb = group.onImpact;
            group.onImpact = null;
            cb(impact);
          }
          if (this.onClashImpact) {
            this.onClashImpact(impact);
          }
        }
      }
    });
  }

  resize(w, h) {
    this.width = w;
    this.height = h;
    this._rebuildWalls(w, h);
  }

  ensureHandCard(key, x, y, w = 196, h = 274) {
    let entry = this.handCards.get(key);
    if (!entry) {
      const { Bodies, Composite } = this.Matter;
      const body = Bodies.rectangle(x, y, w, h, {
        frictionAir: 0,
        restitution: 0,
        density: 0.001,
        collisionFilter: { category: CAT_HAND, mask: 0 },
      });
      Composite.add(this.world, body);
      entry = {
        key,
        body,
        targetX: x,
        targetY: y,
        targetAngle: 0,
        targetScale: 1,
        scale: 1,
        dragging: false,
      };
      this.handCards.set(key, entry);
    }
    return entry;
  }

  pruneHandCards(validKeys) {
    const { Composite } = this.Matter;
    for (const [k, entry] of this.handCards.entries()) {
      if (!validKeys.has(k)) {
        Composite.remove(this.world, entry.body);
        this.handCards.delete(k);
      }
    }
  }

  /**
   * Create two colliding Matter.js bodies directly bound to the two clashing 3D dice.
   */
  createClashDicePair({ cx, cy, radius = 26, outcome = 'draw', winnerColor = 0xe89b32, lungeDelay = 0.34, onImpact = null }) {
    const { Bodies, Composite } = this.Matter;
    this.clearClashGroups();

    const leftBody = Bodies.circle(cx - 210, cy + 45, radius, {
      frictionAir: 0.055,
      restitution: 0.72,
      density: outcome === 'left_win' ? 0.0045 : 0.0022,
      collisionFilter: { category: CAT_DIE, mask: CAT_DIE },
    });
    const rightBody = Bodies.circle(cx + 210, cy - 45, radius, {
      frictionAir: 0.055,
      restitution: 0.72,
      density: outcome === 'right_win' ? 0.0045 : 0.0022,
      collisionFilter: { category: CAT_DIE, mask: CAT_DIE },
    });

    const group = {
      leftBody,
      rightBody,
      cx,
      cy,
      outcome,
      winnerColor,
      lungeDelay,
      onImpact: typeof onImpact === 'function' ? onImpact : null,
      lunged: false,
      collided: false,
      age: 0,
      life: 2.0,
    };
    leftBody._clashGroup = group;
    rightBody._clashGroup = group;
    Composite.add(this.world, [leftBody, rightBody]);
    this.clashGroups.push(group);
    return group;
  }

  clearClashGroups() {
    const { Composite } = this.Matter;
    for (const g of this.clashGroups) {
      Composite.remove(this.world, [g.leftBody, g.rightBody]);
    }
    this.clashGroups = [];
  }

  clearMatch() {
    const { Composite } = this.Matter;
    this.clearClashGroups();
    this.pruneHandCards(new Set());
    Composite.remove(this.world, this.shards.map(shard => shard.body));
    this.shards.length = 0;
  }

  spawnShieldShards(x, y, color, count = 9, eroded = false) {
    const { Bodies, Body, Composite } = this.Matter;
    for (let i = 0; i < count; i++) {
      const sides = eroded ? (3 + (i % 3)) : (4 + (i % 2));
      const r = eroded ? (4.5 + Math.random() * 5) : (4 + Math.random() * 3.8);
      const a = (Math.PI * 2 * i) / count + (Math.random() - 0.5) * 0.55;
      const body = Bodies.polygon(x + Math.cos(a) * 8, y + Math.sin(a) * 8, sides, r, {
        frictionAir: eroded ? 0.045 : 0.06,
        restitution: 0.52,
        density: 0.0012,
        collisionFilter: { category: CAT_SHARD, mask: CAT_WALL | CAT_SHARD },
      });
      const spd = (eroded ? 5.2 : 4.2) + Math.random() * 4.8;
      Body.setVelocity(body, {
        x: Math.cos(a) * spd,
        y: Math.sin(a) * spd + (eroded ? 1.5 : 0),
      });
      Body.setAngularVelocity(body, (Math.random() - 0.5) * 0.38);
      Composite.add(this.world, body);
      this.shards.push({
        body,
        color,
        eroded,
        age: 0,
        life: eroded ? (1.05 + Math.random() * 0.35) : (0.7 + Math.random() * 0.3),
      });
    }
  }

  applyGentleImpulse(x, y, radius = 260, strength = 0.032) {
    const { Body } = this.Matter;
    const push = (body, mult) => {
      const dx = body.position.x - x;
      const dy = body.position.y - y;
      const d = Math.hypot(dx, dy);
      if (d > 1 && d < radius) {
        const f = (1 - d / radius) * strength * mult;
        Body.applyForce(body, body.position, { x: (dx / d) * f, y: (dy / d) * f });
      }
    };
    for (const s of this.shards) push(s.body, 0.85);
  }

  step(dtSec) {
    const { Engine, Body, Composite } = this.Matter;
    const clampedMs = Math.min(50, Math.max(1, dtSec * 1000));
    this.accumulator += clampedMs;

    let steps = 0;
    while (this.accumulator >= FIXED_DT && steps < 4) {
      // Hand cards: strictly overdamped zero-bounce smooth glide (NO rubber-band oscillation!)
      for (const entry of this.handCards.values()) {
        const b = entry.body;
        const gain = entry.dragging ? 0.42 : 0.24;
        const dx = entry.targetX - b.position.x;
        const dy = entry.targetY - b.position.y;
        const vx = Math.abs(dx) < 0.2 ? 0 : dx * gain;
        const vy = Math.abs(dy) < 0.2 ? 0 : dy * gain;
        if (vx === 0 && vy === 0 && (dx !== 0 || dy !== 0)) {
          Body.setPosition(b, { x: entry.targetX, y: entry.targetY });
        }
        Body.setVelocity(b, { x: vx, y: vy });

        const desiredAngle = entry.dragging
          ? Math.max(-0.14, Math.min(0.14, vx * 0.008))
          : entry.targetAngle;
        const da = desiredAngle - b.angle;
        Body.setAngularVelocity(b, Math.abs(da) < 0.001 ? 0 : da * 0.28);
      }

      // Clash dice phases: 0..lungeDelay settle at left/right spots (dice reveal numbers) -> lunge into real collision!
      for (const g of this.clashGroups) {
        g.age += FIXED_DT / 1000;
        const delay = g.lungeDelay ?? 0.34;
        if (!g.lunged) {
          if (g.age < delay) {
            const lx = g.cx - 122;
            const rx = g.cx + 122;
            Body.applyForce(g.leftBody, g.leftBody.position, {
              x: (lx - g.leftBody.position.x) * 0.0022,
              y: (g.cy - g.leftBody.position.y) * 0.0022,
            });
            Body.applyForce(g.rightBody, g.rightBody.position, {
              x: (rx - g.rightBody.position.x) * 0.0022,
              y: (g.cy - g.rightBody.position.y) * 0.0022,
            });
          } else {
            g.lunged = true;
            Body.setVelocity(g.leftBody, { x: 18.5, y: (g.cy - g.leftBody.position.y) * 0.08 });
            Body.setVelocity(g.rightBody, { x: -18.5, y: (g.cy - g.rightBody.position.y) * 0.08 });
          }
        } else if (!g.collided && g.age >= delay + 0.28) {
          g.collided = true;
          const impact = { x: g.cx, y: g.cy, speed: 12, group: g };
          if (g.onImpact) {
            const cb = g.onImpact;
            g.onImpact = null;
            cb(impact);
          }
          if (this.onClashImpact) this.onClashImpact(impact);
        }
      }

      Engine.update(this.engine, FIXED_DT);
      this.accumulator -= FIXED_DT;
      steps++;
    }

    const scaleLerp = Math.min(1, dtSec * 16);
    for (const entry of this.handCards.values()) {
      const ds = entry.targetScale - entry.scale;
      entry.scale = Math.abs(ds) < 0.0008 ? entry.targetScale : entry.scale + ds * scaleLerp;
    }

    for (let i = this.clashGroups.length - 1; i >= 0; i--) {
      if (this.clashGroups[i].age >= this.clashGroups[i].life) {
        const g = this.clashGroups[i];
        Composite.remove(this.world, [g.leftBody, g.rightBody]);
        this.clashGroups.splice(i, 1);
      }
    }

    for (let i = this.shards.length - 1; i >= 0; i--) {
      const s = this.shards[i];
      s.age += dtSec;
      if (s.age >= s.life) {
        Composite.remove(this.world, s.body);
        this.shards.splice(i, 1);
      }
    }
  }
}
