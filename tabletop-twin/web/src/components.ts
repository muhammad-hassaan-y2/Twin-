/**
 * Copyright (c) Meta Platforms, Inc. and affiliates.
 *
 * This source code is licensed under the MIT license found in the
 * LICENSE file in the root directory of this source tree.
 */

import { defineComponents } from '@iwsdk/core';
import {
  ApprovalPrompt,
  BillStone,
  CashBranch,
  FirmPanel,
  ForkRibbon,
  LateBoat,
  RiverFlow,
  SubscriptionPipe,
  TableVoice,
  TimeWheel,
  TwinOrb,
  TwinState,
} from './twin/components.js';

export default defineComponents([
  TwinState,
  RiverFlow,
  BillStone,
  LateBoat,
  SubscriptionPipe,
  CashBranch,
  ForkRibbon,
  TimeWheel,
  TwinOrb,
  TableVoice,
  ApprovalPrompt,
  FirmPanel,
]);
