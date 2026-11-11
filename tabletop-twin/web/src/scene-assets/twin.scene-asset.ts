/**
 * The miniature cash-flow world, built in code so the app downloads no models.
 *
 * Every asset is a parentless, named Object3D authored at a canonical unit size
 * and seated on y = 0, which is the table surface. The twin system scales and
 * places them from the numbers the backend computed; nothing here knows what a
 * dollar is.
 *
 * Palette comes from the backend's colourblind-safe set: no signal in this world
 * is carried by red against green, and every state also changes height, opacity
 * or text.
 */

import {
  BufferGeometry,
  Color,
  ConeGeometry,
  CylinderGeometry,
  DoubleSide,
  Group,
  LatheGeometry,
  Mesh,
  MeshPhysicalMaterial,
  MeshStandardMaterial,
  SphereGeometry,
  TorusGeometry,
  Vector2,
  Vector3,
} from '@iwsdk/core';
import { bevelBox, ensureOutwardWinding, LoftSurface, sampleRange } from './lib/hardsurface.js';

export const PALETTE = {
  river: '#2E7DD1',
  bank: '#7FB3D5',
  stone: '#F2E8C9',
  boat: '#00B3A4',
  lake: '#5BC8AF',
  fog: '#9AA5B1',
  twin: '#FFD166',
  alert: '#E4572E',
  metal: '#B9C4CE',
} as const;

function water(colour: string, opacity = 0.85): MeshPhysicalMaterial {
  return new MeshPhysicalMaterial({
    color: new Color(colour),
    roughness: 0.18,
    metalness: 0,
    transmission: 0.35,
    transparent: true,
    opacity,
    side: DoubleSide,
  });
}

function solid(colour: string, roughness = 0.65, metalness = 0.05): MeshStandardMaterial {
  return new MeshStandardMaterial({ color: new Color(colour), roughness, metalness });
}

function glow(colour: string, intensity = 1.4): MeshStandardMaterial {
  return new MeshStandardMaterial({
    color: new Color(colour),
    emissive: new Color(colour),
    emissiveIntensity: intensity,
    roughness: 0.4,
  });
}

function mesh(name: string, geometry: BufferGeometry, material: MeshStandardMaterial): Mesh {
  const object = new Mesh(geometry, material);
  object.name = name;
  return object;
}

function group(name: string): Group {
  const g = new Group();
  g.name = name;
  return g;
}

/**
 * The river: one unit-length ribbon running +X, 0.12 m wide, top face at y = 0.012.
 * The system scales it to the horizon and re-cuts it per day.
 */
export function createRiverStrip(): Group {
  const root = group('River');
  const surface = mesh('River/Water', new CylinderGeometry(0.06, 0.06, 1, 20, 1, false), water(PALETTE.river, 0.9));
  surface.geometry.rotateZ(Math.PI / 2);
  surface.geometry.scale(1, 0.2, 1);
  surface.geometry.translate(0, 0.012, 0);
  surface.castShadow = false;
  root.add(surface);

  const bed = mesh('River/Bed', bevelBox(1, 0.005, 0.12, 0.002), solid(PALETTE.metal, 0.5, 0.2));
  bed.position.set(0, 0.003, 0);
  bed.castShadow = false;
  root.add(bed);
  return root;
}

/** A translucent bank wall, 1 unit long and 0.20 m tall at rest, seated at y = 0. */
export function createBankWall(): Group {
  const root = group('Bank');
  const wall = mesh('Bank/Wall', bevelBox(1, 0.2, 0.006, 0.006), water(PALETTE.bank, 0.4));
  wall.position.y = 0.1;
  wall.castShadow = false;
  root.add(wall);

  const rail = mesh('Bank/Rail', new CylinderGeometry(0.004, 0.004, 1, 10), solid(PALETTE.metal, 0.35, 0.4));
  rail.geometry.rotateZ(Math.PI / 2);
  rail.position.y = 0.2;
  root.add(rail);
  return root;
}

/** A stepping stone: a squashed, rounded boulder with a flat top you can read as a date. */
export function createStone(): Group {
  const root = group('Stone');
  const body = mesh('Stone/Body', bevelBox(0.062, 0.03, 0.052, 0.014, 0.02, 3), solid(PALETTE.stone, 0.8));
  body.geometry.scale(1, 0.85, 1);
  body.position.y = 0.014;
  root.add(body);

  const cap = mesh('Stone/Cap', new SphereGeometry(0.026, 16, 8, 0, Math.PI * 2, 0, Math.PI / 2.6), solid(PALETTE.stone, 0.72));
  cap.position.y = 0.026;
  cap.castShadow = false;
  root.add(cap);
  return root;
}

/**
 * A late invoice is a boat stuck upstream: a lofted hull, a load on the deck, and
 * a mast the fog wraps around. Long axis is +X, waterline at y = 0.
 */
export function createBoat(): Group {
  const root = group('Boat');
  const loft = LoftSurface.tube([
    { z: -0.036, halfW: 0.004, hUp: 0.006, hDown: 0.002 },
    { z: -0.02, halfW: 0.012, hUp: 0.009, hDown: 0.007 },
    { z: 0, halfW: 0.014, hUp: 0.01, hDown: 0.009 },
    { z: 0.02, halfW: 0.012, hUp: 0.009, hDown: 0.007 },
    { z: 0.036, halfW: 0.005, hUp: 0.007, hDown: 0.002 },
  ]);
  const hull = mesh('Boat/Hull', ensureOutwardWinding(loft.build(sampleRange(-0.036, 0.036, 14), 14, true)), solid(PALETTE.boat, 0.55, 0.1));
  hull.geometry.rotateY(-Math.PI / 2);
  hull.geometry.translate(0, 0.002, 0);
  root.add(hull);

  const load = mesh('Boat/Load', bevelBox(0.03, 0.014, 0.02, 0.004), solid(PALETTE.stone, 0.75));
  load.position.set(0, 0.012, 0);
  root.add(load);

  const mast = mesh('Boat/Mast', new CylinderGeometry(0.0016, 0.0016, 0.05, 8), solid(PALETTE.metal, 0.4, 0.3));
  mast.position.set(-0.012, 0.032, 0);
  root.add(mast);

  const sail = mesh('Boat/Sail', bevelBox(0.026, 0.03, 0.0012, 0.001), glow(PALETTE.alert, 0.25));
  sail.position.set(0.002, 0.036, 0);
  sail.castShadow = false;
  root.add(sail);
  return root;
}

/** Fog whose opacity the system drives from the invoice's own lateness history. */
export function createFogVeil(): Group {
  const root = group('Fog');
  const profile = [
    new Vector2(0.001, 0),
    new Vector2(0.03, 0.001),
    new Vector2(0.042, 0.02),
    new Vector2(0.036, 0.05),
    new Vector2(0.016, 0.072),
    new Vector2(0.001, 0.078),
  ];
  const veil = mesh('Fog/Veil', new LatheGeometry(profile, 22), water(PALETTE.fog, 0.34));
  veil.castShadow = false;
  veil.receiveShadow = false;
  veil.userData.iwsdkPreviewBounds = 'exclude';
  root.add(veil);

  const heart = mesh('Fog/Heart', new SphereGeometry(0.016, 14, 10), water(PALETTE.fog, 0.5));
  heart.position.y = 0.03;
  heart.castShadow = false;
  heart.userData.iwsdkPreviewBounds = 'exclude';
  root.add(heart);
  return root;
}

/** Savings: a shallow, wide disc with a raised rim so it reads as held-back water. */
export function createLake(): Group {
  const root = group('Lake');
  const dish = [
    new Vector2(0.001, 0.004),
    new Vector2(0.07, 0.003),
    new Vector2(0.105, 0.006),
    new Vector2(0.112, 0.014),
    new Vector2(0.115, 0.016),
  ];
  const pool = mesh('Lake/Water', new LatheGeometry(dish, 34), water(PALETTE.lake, 0.8));
  root.add(pool);

  const rim = mesh('Lake/Rim', new TorusGeometry(0.115, 0.006, 10, 40), solid(PALETTE.stone, 0.8));
  rim.geometry.rotateX(Math.PI / 2);
  rim.position.y = 0.014;
  root.add(rim);
  return root;
}

/**
 * The twin: a translucent shell around an emissive core, with a hidden cone
 * aimed down +X so it can point at whatever it is talking about.
 */
export function createOrb(): Group {
  const root = group('Orb');
  const body = group('Orb/Body');
  body.position.y = 0.072;
  root.add(body);
  body.add(mesh('Orb/Core', new SphereGeometry(0.05, 32, 24), glow(PALETTE.twin, 2.1)));
  body.add(mesh('Orb/Shell', new SphereGeometry(0.072, 32, 24), water(PALETTE.twin, 0.22)));
  const ring = mesh('Orb/Ring', new TorusGeometry(0.088, 0.0055, 10, 48), solid(PALETTE.metal, 0.35, 0.6));
  ring.geometry.rotateX(-Math.PI / 2);
  body.add(ring);
  const pointer = mesh('Orb/Pointer', new ConeGeometry(0.021, 0.058, 18), glow(PALETTE.twin, 1.2));
  pointer.geometry.rotateZ(-Math.PI / 2);
  pointer.position.set(0.104, 0, 0);
  pointer.visible = false;
  body.add(pointer);
  return root;
}

/**
 * The time wheel: a flat dial 0.36 m across that twists about Y.
 * Twelve spokes carry the rotation, the handle is where the hand grabs, and the
 * emissive notch opposite it gives the eye something to count against.
 */
export function createTimeWheel(): Group {
  const root = group('Wheel');
  const rim = mesh('Wheel/Rim', new TorusGeometry(0.18, 0.015, 14, 64), solid(PALETTE.metal, 0.4, 0.55));
  rim.geometry.rotateX(-Math.PI / 2);
  rim.position.y = 0.015;
  root.add(rim);
  const hub = mesh('Wheel/Hub', new CylinderGeometry(0.04, 0.046, 0.03, 28), solid(PALETTE.river, 0.45, 0.2));
  hub.position.y = 0.015;
  root.add(hub);
  const axle = mesh('Wheel/Axle', new CylinderGeometry(0.012, 0.012, 0.075, 16), solid(PALETTE.metal, 0.3, 0.7));
  axle.position.y = 0.0375;
  root.add(axle);
  for (let i = 0; i < 12; i += 1) {
    const arm = group('Wheel/Spoke' + i);
    arm.rotation.y = (i * Math.PI) / 6;
    const plate = mesh('Wheel/Spoke/Plate', bevelBox(0.132, 0.008, 0.023, 0.0025), solid(PALETTE.metal, 0.45, 0.5));
    plate.position.set(0.106, 0.013, 0);
    arm.add(plate);
    root.add(arm);
  }
  const handle = mesh('Wheel/Handle', new CylinderGeometry(0.019, 0.019, 0.055, 20), glow(PALETTE.twin, 0.55));
  handle.position.set(0.18, 0.042, 0);
  root.add(handle);
  const notch = mesh('Wheel/Notch', bevelBox(0.03, 0.012, 0.02, 0.003), glow(PALETTE.river, 1.5));
  notch.position.set(-0.18, 0.026, 0);
  root.add(notch);
  return root;
}

/**
 * The subscription pipe: an upright stub that pulls out of the table and springs
 * back. The mouth is the state light; cancelling drains it rather than glazing
 * it over, so the change reads without a colour pair.
 */
export function createPipe(): Group {
  const root = group('Pipe');
  const flange = mesh('Pipe/Flange', new CylinderGeometry(0.052, 0.058, 0.013, 32), solid(PALETTE.metal, 0.5, 0.45));
  flange.position.y = 0.0065;
  root.add(flange);
  const body = mesh('Pipe/Body', new CylinderGeometry(0.027, 0.031, 0.135, 28), solid(PALETTE.boat, 0.5, 0.2));
  body.position.y = 0.0805;
  root.add(body);
  const collar = mesh('Pipe/Collar', new TorusGeometry(0.034, 0.0105, 12, 36), solid(PALETTE.metal, 0.3, 0.7));
  collar.geometry.rotateX(-Math.PI / 2);
  collar.position.y = 0.116;
  root.add(collar);
  const mouth = mesh('Pipe/Mouth', new CylinderGeometry(0.023, 0.023, 0.009, 24), glow(PALETTE.twin, 0.9));
  mouth.position.y = 0.152;
  root.add(mouth);
  for (let i = 0; i < 3; i += 1) {
    const rib = mesh('Pipe/Rib' + i, new TorusGeometry(0.0305, 0.0038, 8, 28), solid(PALETTE.metal, 0.35, 0.6));
    rib.geometry.rotateX(-Math.PI / 2);
    rib.position.y = 0.03 + i * 0.024;
    root.add(rib);
  }
  return root;
}

/**
 * The fork ribbon: a short braided strap that lies on the river and is pulled
 * out toward the viewer to spawn a branch. It has its own node so the grab
 * system owns its transform and the river never has to.
 */
export function createForkRibbon(): Group {
  const root = group('Ribbon');
  const strap = mesh('Ribbon/Strap', bevelBox(0.2, 0.008, 0.026, 0.003), solid(PALETTE.stone, 0.6, 0.05));
  strap.position.y = 0.004;
  root.add(strap);
  for (let i = 0; i < 5; i += 1) {
    const braid = mesh('Ribbon/Braid' + i, new CylinderGeometry(0.0075, 0.0075, 0.034, 12), solid(PALETTE.alert, 0.5, 0.1));
    braid.geometry.rotateZ(Math.PI / 2);
    braid.position.set(-0.07 + i * 0.035, 0.012, 0);
    root.add(braid);
  }
  const tab = mesh('Ribbon/Tab', new CylinderGeometry(0.026, 0.026, 0.012, 24), glow(PALETTE.alert, 0.85));
  tab.geometry.rotateX(-Math.PI / 2);
  tab.position.set(0.115, 0.014, 0);
  root.add(tab);
  return root;
}

/**
 * One garden sprout. The system places five along the lake rim and hides the
 * ones the twin has not earned, so accuracy reads as growth rather than as a
 * number on a dial.
 */
export function createSprout(): Group {
  const root = group('Sprout');
  const stem = mesh('Sprout/Stem', new CylinderGeometry(0.0035, 0.005, 0.07, 10), solid(PALETTE.lake, 0.6, 0.05));
  stem.position.y = 0.035;
  root.add(stem);
  for (let i = 0; i < 2; i += 1) {
    const leaf = mesh('Sprout/Leaf' + i, new SphereGeometry(0.019, 16, 10), solid(PALETTE.lake, 0.55, 0.05));
    leaf.geometry.scale(1, 0.32, 0.6);
    leaf.position.set(i === 0 ? 0.019 : -0.019, 0.044 + i * 0.016, 0);
    leaf.rotation.z = i === 0 ? -0.5 : 0.5;
    root.add(leaf);
  }
  const bud = mesh('Sprout/Bud', new SphereGeometry(0.011, 16, 12), glow(PALETTE.twin, 0.7));
  bud.position.y = 0.076;
  bud.visible = false;
  root.add(bud);
  return root;
}

/**
 * The approval token: a flat coin you pinch and hold. Holding it is the gesture
 * the policy engine waits for, so it has to be something a hand can keep a grip
 * on without moving anything else in the world.
 */
export function createApprovalToken(): Group {
  const root = group('Token');
  const disc = mesh('Token/Disc', new CylinderGeometry(0.034, 0.034, 0.011, 32), glow(PALETTE.twin, 1.1));
  disc.position.y = 0.02;
  root.add(disc);
  const rim = mesh('Token/Rim', new TorusGeometry(0.035, 0.005, 10, 36), solid(PALETTE.metal, 0.3, 0.7));
  rim.geometry.rotateX(-Math.PI / 2);
  rim.position.y = 0.02;
  root.add(rim);
  const slot = mesh('Token/Slot', bevelBox(0.03, 0.004, 0.008, 0.002), solid(PALETTE.alert, 0.5, 0.2));
  slot.position.y = 0.026;
  root.add(slot);
  return root;
}
