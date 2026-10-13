import React from 'react';

export interface CardProps {
  title?: string;
  children: React.ReactNode;
  className?: string;
  as?: 'section' | 'article' | 'div';
}

const cardStyle: React.CSSProperties = {
  background: 'var(--surface-card)',
  border: '1px solid var(--border-control)',
  borderRadius: 'var(--radius-md)',
  boxShadow: 'var(--shadow-card)',
  padding: 'var(--space-4) var(--space-6)',
  transition: 'box-shadow var(--transition-fast)',
};

const titleStyle: React.CSSProperties = {
  fontFamily: 'var(--font-ui)',
  fontSize: 'var(--text-md)',
  fontWeight: 'var(--weight-semibold)',
  lineHeight: 'var(--leading-snug)',
  color: 'var(--text-primary)',
  marginTop: 0,
  marginBottom: 'var(--space-4)',
};

export function Card({ title, children, className, as: Tag = 'section' }: CardProps): React.ReactElement {
  return (
    <Tag
      className={`panel-card${className ? ` ${className}` : ''}`}
      style={cardStyle}
    >
      {title && <h2 style={titleStyle}>{title}</h2>}
      {children}
    </Tag>
  );
}
