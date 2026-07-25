import { FormControl, InputLabel, Select, MenuItem, SelectChangeEvent } from '@mui/material';
import { useAppDispatch, useAppSelector } from '../../../app/hooks';
import { setSelectedATS, setSelectedCompanyId } from '../../../features/app/appSlice';
import {
  useCompanyRegistry,
  useGetCompanyById,
} from '../../../features/userCompanies/useCompanyRegistry';
import { ATSConstants } from '../../../api/types';

/**
 * Company selector dropdown
 */
export function CompanySelector() {
  const dispatch = useAppDispatch();
  const selectedCompanyId = useAppSelector((state) => state.app.selectedCompanyId);
  const companies = useCompanyRegistry();
  const getCompanyById = useGetCompanyById();

  const handleCompanyChange = (event: SelectChangeEvent) => {
    const newCompanyId = event.target.value;
    dispatch(setSelectedCompanyId(newCompanyId));
    dispatch(setSelectedATS(getCompanyById(newCompanyId)?.ats ?? ATSConstants.BackendScraper));
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
        {[...companies].sort((a, b) => a.name.localeCompare(b.name)).map((company) => (
          <MenuItem key={company.id} value={company.id}>
            {company.name}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  );
}
