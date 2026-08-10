/**
 * The tier gate both 3D prototype entries run BEFORE deciding whether to mount
 * their nested-lazy scene. All environment reads happen here (probed once per
 * mount — none of them meaningfully change while mounted); every decision
 * branch lives in the pure `resolveExperienceTier`.
 */
import { useMemo, useState } from 'react';
import { useIsMobile } from '../../../../hooks/useIsMobile';
import { usePrefersReducedMotion } from '../../usePrefersReducedMotion';
import { detectWebGLSupport } from './detectWebGL';
import { resolveExperienceTier, type ExperienceTierResult } from './experienceTier';

export interface HardwareHints {
  hardwareConcurrency?: number;
  deviceMemory?: number;
}

/** Reads the navigator's capability hints; navigator injectable for tests. */
export function readHardwareHints(
  nav: Navigator | undefined = typeof navigator === 'undefined' ? undefined : navigator
): HardwareHints {
  if (!nav) return {};
  // deviceMemory is Chromium-only and absent from lib.dom's Navigator type.
  const { deviceMemory } = nav as Navigator & { deviceMemory?: number };
  return {
    hardwareConcurrency:
      typeof nav.hardwareConcurrency === 'number' ? nav.hardwareConcurrency : undefined,
    deviceMemory: typeof deviceMemory === 'number' ? deviceMemory : undefined,
  };
}

export interface ExperienceTierState extends ExperienceTierResult {
  isMobileViewport: boolean;
}

export function useExperienceTier(): ExperienceTierState {
  const prefersReducedMotion = usePrefersReducedMotion();
  const isMobileViewport = useIsMobile();
  // useState initializers: probed exactly once per mount, re-render safe.
  const [webglSupported] = useState(detectWebGLSupport);
  const [hints] = useState(readHardwareHints);
  return useMemo(
    () => ({
      ...resolveExperienceTier({
        prefersReducedMotion,
        webglSupported,
        isMobileViewport,
        hardwareConcurrency: hints.hardwareConcurrency,
        deviceMemory: hints.deviceMemory,
      }),
      isMobileViewport,
    }),
    [prefersReducedMotion, webglSupported, isMobileViewport, hints]
  );
}
