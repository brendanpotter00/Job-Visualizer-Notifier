import { useEffect, useMemo } from 'react';
import { useTexture } from '@react-three/drei';
import { RigidBody } from '@react-three/rapier';
import { BoxGeometry, MeshLambertMaterial, SRGBColorSpace, type Texture } from 'three';

export type TileTone = 'grayscale' | 'brand';

/**
 * Shared across every tile — one geometry and one edge material for the whole
 * pile. Module-scope is safe: this module only ever loads inside the lazy
 * Gravity scene chunk, and the singletons live for the lifetime of the scene.
 */
const TILE_GEOMETRY = new BoxGeometry(1, 1, 0.14);
const EDGE_MATERIAL = new MeshLambertMaterial({ color: '#d9d9d9' });

/**
 * Cheapest possible grayscale: rewrite the sampled map color to its Rec. 709
 * luminance in the fragment shader. No canvas pre-processing, no extra
 * textures — one string splice at compile time. All grayscale tiles share one
 * GL program via the explicit cache key.
 */
function applyGrayscale(material: MeshLambertMaterial): void {
  material.onBeforeCompile = (shader) => {
    shader.fragmentShader = shader.fragmentShader.replace(
      '#include <map_fragment>',
      [
        '#include <map_fragment>',
        'diffuseColor.rgb = vec3(dot(diffuseColor.rgb, vec3(0.2126, 0.7152, 0.0722)));',
      ].join('\n')
    );
  };
  material.customProgramCacheKey = () => 'logo-tile-grayscale';
}

function applySrgb(texture: Texture | Texture[]): void {
  for (const item of Array.isArray(texture) ? texture : [texture]) {
    item.colorSpace = SRGBColorSpace;
  }
}

interface LogoTileBodyProps {
  logoUrl: string;
  position: [number, number, number];
  rotation: [number, number, number];
  tone: TileTone;
  onSleep: () => void;
  onWake: () => void;
}

/**
 * One physical logo tile: a rapier RigidBody around a box mesh whose ±z faces
 * carry the company logo (BoxGeometry group order is +x, -x, +y, -y, +z, -z)
 * and whose four edges share EDGE_MATERIAL. Suspends via useTexture until the
 * logo PNG arrives.
 */
export function LogoTileBody({
  logoUrl,
  position,
  rotation,
  tone,
  onSleep,
  onWake,
}: LogoTileBodyProps) {
  const texture = useTexture(logoUrl, applySrgb);

  const faceMaterial = useMemo(() => {
    const material = new MeshLambertMaterial({ map: texture });
    if (tone === 'grayscale') applyGrayscale(material);
    return material;
  }, [texture, tone]);

  useEffect(() => () => faceMaterial.dispose(), [faceMaterial]);

  const materials = useMemo(
    () => [
      EDGE_MATERIAL,
      EDGE_MATERIAL,
      EDGE_MATERIAL,
      EDGE_MATERIAL,
      faceMaterial,
      faceMaterial,
    ],
    [faceMaterial]
  );

  return (
    <RigidBody
      colliders="cuboid"
      position={position}
      rotation={rotation}
      linearDamping={0.15}
      ccd
      restitution={0.2}
      friction={0.8}
      onSleep={onSleep}
      onWake={onWake}
    >
      <mesh geometry={TILE_GEOMETRY} material={materials} />
    </RigidBody>
  );
}
