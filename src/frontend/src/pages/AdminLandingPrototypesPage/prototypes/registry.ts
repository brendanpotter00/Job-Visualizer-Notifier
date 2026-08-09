/**
 * Prototype tab registry. Every prototype is behind React.lazy — the first
 * lazy boundaries in this codebase — so each design (and, later, the three.js
 * chunks inside the 3D tabs) stays out of the main bundle. React.lazy needs
 * default exports, so each prototype entry file exports BOTH named (tests) and
 * default (lazy) — an accepted, documented deviation from the named-export
 * convention, confined to these four entries.
 */
import { lazy, type ComponentType, type LazyExoticComponent } from 'react';
import type { LandingPrototypeProps, PrototypeId } from '../types';

export interface PrototypeRegistryEntry {
  id: PrototypeId;
  /** Tab label shown in the browser-style strip. */
  label: string;
  Component: LazyExoticComponent<ComponentType<LandingPrototypeProps>>;
}

export const PROTOTYPES: readonly PrototypeRegistryEntry[] = [
  {
    id: 'signal',
    label: 'Signal',
    Component: lazy(() => import('./SignalPrototype/SignalPrototype')),
  },
  {
    id: 'board',
    label: 'The Board',
    Component: lazy(() => import('./BoardPrototype/BoardPrototype')),
  },
  {
    id: 'gravity',
    label: 'Gravity',
    Component: lazy(() => import('./GravityPrototype/GravityPrototype')),
  },
  {
    id: 'drift',
    label: 'Drift',
    Component: lazy(() => import('./DriftPrototype/DriftPrototype')),
  },
];
