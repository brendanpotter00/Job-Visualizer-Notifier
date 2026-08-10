/**
 * The Drift particle scene — loads only through DriftPrototype's nested
 * React.lazy, so fallback tiers never download three. Thin JSX plumbing: all
 * numbers live in the pure particlesConfig module.
 */
import { useEffect } from 'react';
import { Canvas, useThree } from '@react-three/fiber';
import { Sparkles } from '@react-three/drei';
import { resolveFrameloop } from '../shared3d/experienceTier';
import type { DriftParticlesConfig } from './particlesConfig';

/** Monochrome gray — the field must stay ≤10% visual weight. */
const DOT_COLOR = '#8a8a8a';

/**
 * Gravity's settle governor minus the sleep input: particles never sleep, so
 * only hero visibility (IntersectionObserver on the canvas) and tab visibility
 * park the frameloop. The jsdom test setup stubs IntersectionObserver as a
 * no-op class — heroInView then just keeps its default (true).
 */
function useVisibilityFrameloop(): void {
  const setFrameloop = useThree((state) => state.setFrameloop);
  const gl = useThree((state) => state.gl);

  useEffect(() => {
    let heroInView = true;
    let docVisible = document.visibilityState !== 'hidden';
    const apply = () =>
      setFrameloop(resolveFrameloop({ allAsleep: false, heroInView, docVisible }));

    const handleVisibility = () => {
      docVisible = document.visibilityState !== 'hidden';
      apply();
    };
    document.addEventListener('visibilitychange', handleVisibility);

    let observer: IntersectionObserver | undefined;
    if (typeof IntersectionObserver === 'function') {
      observer = new IntersectionObserver((entries) => {
        const entry = entries[entries.length - 1];
        if (entry) {
          heroInView = entry.isIntersecting;
          apply();
        }
      });
      observer.observe(gl.domElement);
    }
    apply();
    return () => {
      document.removeEventListener('visibilitychange', handleVisibility);
      observer?.disconnect();
    };
  }, [gl, setFrameloop]);
}

function DriftSceneContent({ config }: { config: DriftParticlesConfig }) {
  useVisibilityFrameloop();
  return (
    <>
      <Sparkles
        count={config.jobs.count}
        size={config.jobs.size}
        scale={config.jobs.scale}
        speed={config.jobs.speed}
        opacity={config.jobs.opacity}
        color={DOT_COLOR}
      />
      <Sparkles
        count={config.ambient.count}
        size={config.ambient.size}
        scale={config.ambient.scale}
        speed={config.ambient.speed}
        opacity={config.ambient.opacity}
        color={DOT_COLOR}
        position={[0, 0, -4]}
      />
    </>
  );
}

export interface DriftSceneProps {
  config: DriftParticlesConfig;
  /** Upper bound of the Canvas dpr clamp (from the experience tier). */
  maxDpr: number;
}

export function DriftScene({ config, maxDpr }: DriftSceneProps) {
  return (
    <Canvas dpr={[1, maxDpr]} camera={{ position: [0, 0, 10], fov: 45 }} frameloop="always">
      <DriftSceneContent config={config} />
    </Canvas>
  );
}

export default DriftScene;
