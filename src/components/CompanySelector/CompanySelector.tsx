import { FormControl, InputLabel, Select, MenuItem, SelectChangeEvent } from '@mui/material';
import { useAppDispatch, useAppSelector } from '../../app/hooks';
import { selectCompany } from '../../features/app/appSlice';
import { COMPANIES } from '../../config/companies';

/**
 * Company selector dropdown
 */
export function CompanySelector() {
  const dispatch = useAppDispatch();
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);

  const handleCompanyChange = (event: SelectChangeEvent) => {
    const newCompanyId = event.target.value;
    dispatch(selectCompany(newCompanyId));
    // useCompanyLoader hook (in App.tsx) handles loading jobs automatically
  };

  return (
    <FormControl sx={{ minWidth: 200 }}>
      <InputLabel id="company-selector-label">Company</InputLabel>
      <Select
        labelId="company-selector-label"
        id="company-selector"
        value={selectedCompanyId}
        label="Company"
        onChange={handleCompanyChange}
      >
        {COMPANIES.map((company) => (
          <MenuItem key={company.id} value={company.id}>
            {company.name}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
