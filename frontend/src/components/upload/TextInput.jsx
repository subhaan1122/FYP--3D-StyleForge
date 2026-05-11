import React from 'react';
import { MessageSquare } from 'lucide-react';
import '../../styles/components/text-input.css';

const TextInput = ({
  value,
  onChange,
  placeholder = 'Describe your outfit...',
  label = 'Description',
  required = false,
  disabled = false,
  rows = 4,
  maxLength = 500,
}) => {
  const handleChange = (e) => {
    if (onChange) {
      onChange(e.target.value);
    }
  };

  return (
    <div className="text-input">
      {label && (
        <div className="text-input-label">
          <span>{label}</span>
          {required && <span className="required">*</span>}
          {maxLength && (
            <span className="character-count">
              {value.length}/{maxLength}
            </span>
          )}
        </div>
      )}
      
      <div className="text-input-wrapper">
        <MessageSquare className="text-input-icon" size={20} />
        <textarea
          value={value}
          onChange={handleChange}
          placeholder={placeholder}
          rows={rows}
          maxLength={maxLength}
          disabled={disabled}
          className="text-input-field"
        />
      </div>
      
      <div className="text-input-help">
        <p>Example: "a red leather jacket with black jeans"</p>
      </div>
    </div>
  );
};

export default TextInput;