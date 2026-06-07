import React from 'react';
import {AbsoluteFill, Sequence} from 'remotion';
import {IngestionPipeline, LOOP_FRAMES} from './IngestionPipeline';
import {WebscraperPipeline, WEBSCRAPER_LOOP_FRAMES} from './WebscraperPipeline';

// Both segments are internally seamless loops that start and end idle, so a
// hard cut between them (and across the video's own loop boundary) is clean.
export const COMBINED_FRAMES = LOOP_FRAMES + WEBSCRAPER_LOOP_FRAMES; // 1290 = 43s

export const CombinedPipelines: React.FC = () => {
  return (
    <AbsoluteFill>
      <Sequence durationInFrames={LOOP_FRAMES}>
        <IngestionPipeline />
      </Sequence>
      <Sequence from={LOOP_FRAMES} durationInFrames={WEBSCRAPER_LOOP_FRAMES}>
        <WebscraperPipeline />
      </Sequence>
    </AbsoluteFill>
  );
};
