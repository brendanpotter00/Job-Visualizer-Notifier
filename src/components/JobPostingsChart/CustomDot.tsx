import type { TimeBucket } from '../../types';

/**
 * Props for CustomDot component
 */
export interface CustomDotProps {
  cx?: number;
  cy?: number;
  r?: number;
  fill?: string;
  stroke?: string;
  strokeWidth?: number;
  payload?: {
    bucket?: TimeBucket;
  };
  onPointClick?: (bucket: TimeBucket) => void;
}

/**
 * Custom dot component that handles clicks on chart data points
 * Allows users to click on a point to see jobs posted in that time bucket
 */
export function CustomDot({ cx, cy, r = 4, fill, payload, onPointClick }: CustomDotProps) {
  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    if (payload?.bucket && onPointClick) {
      onPointClick(payload.bucket);
    }
  };

  return <circle cx={cx} cy={cy} r={r} fill={fill} cursor="pointer" onClick={handleClick} />;
}
