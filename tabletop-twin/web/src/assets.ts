/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { AssetType, defineAssets } from '@iwsdk/core';
import {
  createApprovalToken,
  createBankWall,
  createBoat,
  createFogVeil,
  createForkRibbon,
  createLake,
  createOrb,
  createPipe,
  createRiverStrip,
  createSprout,
  createStone,
  createTimeWheel,
} from './scene-assets/twin.scene-asset.js';

const publicAssetUrl = (filePath: string): string =>
  `${import.meta.env.BASE_URL}${filePath.replace(/^\/+/u, '')}`;

const uikitml = (fileName: string, name: string) => ({
  url: publicAssetUrl(`ui/${fileName}`),
  type: AssetType.UIKitML,
  name,
});

export default defineAssets({
  'twin-river': createRiverStrip(),
  'twin-bank': createBankWall(),
  'twin-stone': createStone(),
  'twin-boat': createBoat(),
  'twin-fog': createFogVeil(),
  'twin-lake': createLake(),
  'twin-orb': createOrb(),
  'twin-wheel': createTimeWheel(),
  'twin-pipe': createPipe(),
  'twin-ribbon': createForkRibbon(),
  'twin-sprout': createSprout(),
  'twin-token': createApprovalToken(),
  'twin-captions': uikitml('captions.uikitml', 'Captions'),
  'twin-approve': uikitml('approve.uikitml', 'Approval prompt'),
});
