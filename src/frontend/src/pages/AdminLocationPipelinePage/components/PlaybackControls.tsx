import Box from '@mui/material/Box';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import MenuItem from '@mui/material/MenuItem';
import Select, { type SelectChangeEvent } from '@mui/material/Select';
import Tooltip from '@mui/material/Tooltip';
import Typography from '@mui/material/Typography';
import PlayArrowIcon from '@mui/icons-material/PlayArrow';
import PauseIcon from '@mui/icons-material/Pause';
import SkipNextIcon from '@mui/icons-material/SkipNext';
import SkipPreviousIcon from '@mui/icons-material/SkipPrevious';
import RestartAltIcon from '@mui/icons-material/RestartAlt';
import type { PipelineExample } from '../fixtures';

interface PlaybackControlsProps {
  examples: PipelineExample[];
  exampleIndex: number;
  onSelect: (index: number) => void;
  isPlaying: boolean;
  onToggle: () => void;
  onStepBack: () => void;
  onStepForward: () => void;
  onRestart: () => void;
  currentStageIndex: number;
  totalStages: number;
}

/** Example picker + transport controls (step / play / restart). */
export function PlaybackControls({
  examples,
  exampleIndex,
  onSelect,
  isPlaying,
  onToggle,
  onStepBack,
  onStepForward,
  onRestart,
  currentStageIndex,
  totalStages,
}: PlaybackControlsProps) {
  const handleChange = (event: SelectChangeEvent) => onSelect(Number(event.target.value));

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
      <Select
        size="small"
        value={String(exampleIndex)}
        onChange={handleChange}
        inputProps={{ 'aria-label': 'Choose example' }}
        sx={{ minWidth: 240 }}
      >
        {examples.map((example, index) => (
          <MenuItem key={example.id} value={String(index)}>
            {example.label}
          </MenuItem>
        ))}
      </Select>

      <Tooltip title="Step back">
        <IconButton onClick={onStepBack} aria-label="Step back" size="small">
          <SkipPreviousIcon />
        </IconButton>
      </Tooltip>

      <Tooltip title={isPlaying ? 'Pause' : 'Play'}>
        <IconButton onClick={onToggle} aria-label={isPlaying ? 'Pause' : 'Play'} color="primary">
          {isPlaying ? <PauseIcon /> : <PlayArrowIcon />}
        </IconButton>
      </Tooltip>

      <Tooltip title="Step forward">
        <IconButton onClick={onStepForward} aria-label="Step forward" size="small">
          <SkipNextIcon />
        </IconButton>
      </Tooltip>

      <Button onClick={onRestart} startIcon={<RestartAltIcon />} size="small" variant="outlined">
        Restart
      </Button>

      <Typography
        variant="caption"
        sx={{ ml: 'auto', fontFamily: 'monospace', color: 'text.secondary' }}
      >
        Stage {currentStageIndex + 1} / {totalStages}
      </Typography>
    </Box>
  );
}
