import React from 'react';
import { Loader2 } from 'lucide-react';
import '../../styles/components/button.css';

const Button = ({
  children,
  variant = 'primary',
  size = 'medium',
  loading = false,
  disabled = false,
  fullWidth = false,
  onClick,
  className = '',
  type = 'button',
  icon: Icon,
  iconPosition = 'left',
}) => {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || loading}
      className={`
        button 
        button-${variant} 
        button-${size}
        ${fullWidth ? 'button-full-width' : ''}
        ${loading ? 'button-loading' : ''}
        ${className}
      `}
    >
      {loading && (
        <span className="button-spinner">
          <Loader2 size={size === 'small' ? 16 : 20} />
        </span>
      )}
      
      {!loading && Icon && iconPosition === 'left' && (
        <span className="button-icon-left">
          <Icon size={size === 'small' ? 16 : 20} />
        </span>
      )}
      
      <span className="button-text">
        {children}
      </span>
      
      {!loading && Icon && iconPosition === 'right' && (
        <span className="button-icon-right">
          <Icon size={size === 'small' ? 16 : 20} />
        </span>
      )}
    </button>
  );
};

export default Button;