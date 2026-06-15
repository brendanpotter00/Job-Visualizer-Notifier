import { Fragment } from 'react';
import Box from '@mui/material/Box';
import { StageNode, type NodeState } from './StageNode';
import { FlowConnector } from './FlowConnector';
import type { Branch, StageMeta } from '../fixtures';
import type { Phase } from '../usePipelinePlayer';

interface PipelineRailProps {
  stages: StageMeta[];
  path: number[];
  cursor: number;
  currentStageIndex: number;
  branch: Branch;
  phase: Phase;
}

/** The horizontal rail of seven stage nodes with animated connectors. */
export function PipelineRail({
  stages,
  path,
  cursor,
  currentStageIndex,
  phase,
}: PipelineRailProps) {
  function nodeState(i: number): NodeState {
    if (!path.includes(i)) return 'skipped';
    if (i === currentStageIndex) {
      return phase === 'failed' && i === 4 ? 'failed' : 'active';
    }
    return path.indexOf(i) < cursor ? 'done' : 'idle';
  }

  return (
    <Box sx={{ overflowX: 'auto', py: 2.5, px: 1 }}>
      <Box sx={{ display: 'flex', alignItems: 'stretch', minWidth: 860 }}>
        {stages.map((meta, i) => (
          <Fragment key={meta.id}>
            {i > 0 && (
              <FlowConnector
                lit={currentStageIndex >= i}
                flowing={i === currentStageIndex && cursor > 0}
                flowKey={cursor}
              />
            )}
            <StageNode meta={meta} index={i} state={nodeState(i)} />
          </Fragment>
        ))}
      </Box>
    </Box>
  );
}
