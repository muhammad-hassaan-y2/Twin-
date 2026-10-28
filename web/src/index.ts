/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { World } from '@iwsdk/core';
import projectOptions from 'virtual:iwsdk-project';
import { TwinHandsSystem } from './twin/hands.js';
import { TwinVoiceSystem } from './twin/voice.js';
import { TwinWorldSystem } from './twin/world-system.js';

World.create(
  document.getElementById('scene-container') as HTMLDivElement,
  projectOptions,
).then((world) => {
  world.registerSystem(TwinWorldSystem);
  world.registerSystem(TwinHandsSystem);
  world.registerSystem(TwinVoiceSystem);
});
