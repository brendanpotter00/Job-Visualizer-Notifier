import {
  Box,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  FormControlLabel,
  Switch,
  Stack,
  TextField,
} from '@mui/material';
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import {
  setListTimeWindow,
  setListLocation,
  setListDepartment,
  setListRoleCategory,
  setListSearchQuery,
  toggleListSoftwareOnly,
} from '../../features/filters/filtersSlice';
import {
  selectListFilters,
  selectAvailableLocations,
  selectAvailableDepartments,
} from '../../features/filters/filtersSelectors';
import type { TimeWindow, SoftwareRoleCategory } from '../../types';

const TIME_WINDOWS: { value: TimeWindow; label: string }[] = [
  { value: '30m', label: '30 minutes' },
  { value: '1h', label: '1 hour' },
  { value: '3h', label: '3 hours' },
  { value: '6h', label: '6 hours' },
  { value: '12h', label: '12 hours' },
  { value: '24h', label: '24 hours' },
  { value: '3d', label: '3 days' },
  { value: '7d', label: '7 days' },
  { value: '14d', label: '14 days' },
  { value: '30d', label: '30 days' },
  { value: '90d', label: '90 days' },
  { value: '180d', label: '6 months' },
  { value: '1y', label: '1 year' },
  { value: '2y', label: '2 years' },
];

const ROLE_CATEGORIES: { value: SoftwareRoleCategory | 'all'; label: string }[] = [
  { value: 'all', label: 'All Categories' },
  { value: 'frontend', label: 'Frontend' },
  { value: 'backend', label: 'Backend' },
  { value: 'fullstack', label: 'Full Stack' },
  { value: 'mobile', label: 'Mobile' },
  { value: 'data', label: 'Data' },
  { value: 'ml', label: 'ML/AI' },
  { value: 'devops', label: 'DevOps' },
  { value: 'platform', label: 'Platform' },
  { value: 'qa', label: 'QA' },
  { value: 'security', label: 'Security' },
];

/**
 * Filter controls for the job list
 */
export function ListFilters() {
  const dispatch = useAppDispatch();
  const filters = useAppSelector(selectListFilters);
  const availableLocations = useAppSelector(selectAvailableLocations);
  const availableDepartments = useAppSelector(selectAvailableDepartments);

  return (
    <Box sx={{ mb: 3 }}>
      <Stack spacing={2}>
        <TextField
          size="small"
          placeholder="Search jobs by title, department, location..."
          value={filters.searchQuery || ''}
          onChange={(e) => {
            const value = e.target.value;
            dispatch(setListSearchQuery(value || undefined));
          }}
          fullWidth
        />

        <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2}>
          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Time Window</InputLabel>
            <Select
              value={filters.timeWindow}
              label="Time Window"
              onChange={(e) => dispatch(setListTimeWindow(e.target.value as TimeWindow))}
            >
              {TIME_WINDOWS.map((tw) => (
                <MenuItem key={tw.value} value={tw.value}>
                  {tw.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          <FormControl size="small" sx={{ minWidth: 150 }}>
            <InputLabel>Role Category</InputLabel>
            <Select
              value={filters.roleCategory || 'all'}
              label="Role Category"
              onChange={(e) =>
                dispatch(setListRoleCategory(e.target.value as SoftwareRoleCategory | 'all'))
              }
            >
              {ROLE_CATEGORIES.map((cat) => (
                <MenuItem key={cat.value} value={cat.value}>
                  {cat.label}
                </MenuItem>
              ))}
            </Select>
          </FormControl>

          {availableLocations.length > 0 && (
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>Location</InputLabel>
              <Select
                value={filters.location || ''}
                label="Location"
                onChange={(e) => dispatch(setListLocation(e.target.value || undefined))}
              >
                <MenuItem value="">All Locations</MenuItem>
                {availableLocations.map((loc) => (
                  <MenuItem key={loc} value={loc}>
                    {loc}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}

          {availableDepartments.length > 0 && (
            <FormControl size="small" sx={{ minWidth: 150 }}>
              <InputLabel>Department</InputLabel>
              <Select
                value={filters.department || ''}
                label="Department"
                onChange={(e) => dispatch(setListDepartment(e.target.value || undefined))}
              >
                <MenuItem value="">All Departments</MenuItem>
                {availableDepartments.map((dept) => (
                  <MenuItem key={dept} value={dept}>
                    {dept}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
          )}
        </Stack>

        <Stack direction="row" spacing={2} alignItems="center">
          <FormControlLabel
            control={
              <Switch checked={filters.softwareOnly} onChange={() => dispatch(toggleListSoftwareOnly())} />
            }
            label="Software roles only"
          />
        </Stack>
      </Stack>
    </Box>
  );
}
