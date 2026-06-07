import {Composition} from 'remotion';
import {BackendArchitecture, DURATION_IN_FRAMES, FPS} from './BackendArchitecture';
import {IngestionPipeline, LOOP_FRAMES} from './IngestionPipeline';
import {WebscraperPipeline, WEBSCRAPER_LOOP_FRAMES} from './WebscraperPipeline';
import {CombinedPipelines, COMBINED_FRAMES} from './CombinedPipelines';

export const RemotionRoot: React.FC = () => {
  return (
    <>
      <Composition
        id="CombinedPipelines"
        component={CombinedPipelines}
        durationInFrames={COMBINED_FRAMES}
        fps={FPS}
        width={1920}
        height={1080}
      />
      <Composition
        id="IngestionPipeline"
        component={IngestionPipeline}
        durationInFrames={LOOP_FRAMES}
        fps={FPS}
        width={1920}
        height={1080}
      />
      <Composition
        id="WebscraperPipeline"
        component={WebscraperPipeline}
        durationInFrames={WEBSCRAPER_LOOP_FRAMES}
        fps={FPS}
        width={1920}
        height={1080}
      />
      <Composition
        id="BackendArchitecture"
        component={BackendArchitecture}
        durationInFrames={DURATION_IN_FRAMES}
        fps={FPS}
        width={1920}
        height={1080}
      />
    </>
  );
};
