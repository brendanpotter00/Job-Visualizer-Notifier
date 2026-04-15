import Typography from '@mui/material/Typography';

interface SubsectionTitleProps {
  children: string;
}

export function SubsectionTitle({ children }: SubsectionTitleProps) {
  return (
    <Typography
      component="h3"
      sx={{
        fontSize: '1.38rem',
        fontWeight: 700,
        letterSpacing: '-0.25px',
        color: '#26251e',
        mb: 2,
      }}
    >
      {children}
    </Typography>
  );
}
