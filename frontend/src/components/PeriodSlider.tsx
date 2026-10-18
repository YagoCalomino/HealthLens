import React from 'react';
import * as Slider from '@radix-ui/react-slider';

interface PeriodSliderProps {
  anoInicio: number;
  anoFim: number;
  onChange: (inicio: number, fim: number) => void;
  min?: number;
  max?: number;
}

export function PeriodSlider({
  anoInicio,
  anoFim,
  onChange,
  min = 2010,
  max = 2026,
}: PeriodSliderProps): React.ReactElement {
  const rawInicio = Number(anoInicio);
  const rawFim = Number(anoFim);
  const safeMin = Number(min ?? 2010);
  const safeMax = Number(max ?? 2026);

  // Clamp inicio between min and max-1
  const safeInicio = Number.isFinite(rawInicio)
    ? Math.max(safeMin, Math.min(rawInicio, safeMax - 1))
    : safeMin;

  // Clamp fim between inicio+1 and max
  const safeFim = Number.isFinite(rawFim)
    ? Math.max(safeInicio + 1, Math.min(rawFim, safeMax))
    : safeMax;

  return (
    <div style={{ padding: '4px 0' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 10 }}>
        <span style={{ fontFamily: 'IBM Plex Mono, monospace', fontSize: 13, color: '#E6EDF3', fontWeight: 500 }}>
          {safeInicio}
        </span>
        <span style={{ fontSize: 11, color: '#6B7689' }}>até</span>
        <span style={{ fontFamily: 'IBM Plex Mono, monospace', fontSize: 13, color: '#E6EDF3', fontWeight: 500 }}>
          {safeFim}
        </span>
      </div>

      <Slider.Root
        min={safeMin}
        max={safeMax}
        step={1}
        minStepsBetweenThumbs={1}
        value={[safeInicio, safeFim]}
        onValueChange={(values: number[]) => {
          if (values.length === 2 && values[0] !== values[1]) {
            onChange(values[0], values[1]);
          }
        }}
        style={{
          position: 'relative',
          display: 'flex',
          alignItems: 'center',
          userSelect: 'none',
          touchAction: 'none',
          width: '100%',
          height: '20px',
        }}
      >
        <Slider.Track
          style={{
            backgroundColor: '#1B2230',
            position: 'relative',
            flexGrow: 1,
            borderRadius: '9999px',
            height: '4px',
          }}
        >
          <Slider.Range
            style={{
              position: 'absolute',
              backgroundColor: '#3F6FFF',
              borderRadius: '9999px',
              height: '100%',
            }}
          />
        </Slider.Track>

        <Slider.Thumb
          aria-label="Ano início"
          style={{
            display: 'block',
            width: '16px',
            height: '16px',
            backgroundColor: 'white',
            borderRadius: '50%',
            boxShadow: '0 2px 8px rgba(0,0,0,0.5)',
            cursor: 'pointer',
            outline: 'none',
          }}
        />
        <Slider.Thumb
          aria-label="Ano fim"
          style={{
            display: 'block',
            width: '16px',
            height: '16px',
            backgroundColor: 'white',
            borderRadius: '50%',
            boxShadow: '0 2px 8px rgba(0,0,0,0.5)',
            cursor: 'pointer',
            outline: 'none',
          }}
        />
      </Slider.Root>
    </div>
  );
}
