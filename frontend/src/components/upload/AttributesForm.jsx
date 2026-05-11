import React, { useState } from 'react';
import { Palette, Shirt, Ruler, Droplets, Zap } from 'lucide-react';
import '../../styles/components/attributes-form.css';

const AttributesForm = ({ onAttributesChange, initialValues = {} }) => {
  const [attributes, setAttributes] = useState({
    garment_type: initialValues.garment_type || '',
    color: initialValues.color || '',
    style: initialValues.style || '',
    fit: initialValues.fit || '',
    sleeve_length: initialValues.sleeve_length || '',
    pattern: initialValues.pattern || '',
    material: initialValues.material || '',
  });

  const garmentTypes = ['t-shirt', 'shirt', 'jacket', 'hoodie', 'sweater', 'dress', 'blouse'];
  const colors = ['black', 'white', 'red', 'blue', 'green', 'yellow', 'pink', 'purple', 'gray', 'brown'];
  const styles = ['casual', 'formal', 'sporty', 'vintage', 'modern', 'bohemian', 'minimalist'];
  const fits = ['slim', 'regular', 'loose', 'oversized', 'tailored'];
  const sleeveLengths = ['short', 'long', 'sleeveless', 'three-quarter'];
  const patterns = ['solid', 'striped', 'checked', 'floral', 'geometric', 'print', 'plain'];
  const materials = ['cotton', 'denim', 'leather', 'silk', 'wool', 'polyester', 'linen'];

  const handleChange = (field, value) => {
    const newAttributes = { ...attributes, [field]: value };
    setAttributes(newAttributes);
    if (onAttributesChange) {
      onAttributesChange(newAttributes);
    }
  };

  const generateInstruction = () => {
    const parts = [];
    
    if (attributes.garment_type) parts.push(`a ${attributes.garment_type}`);
    if (attributes.color) parts.push(attributes.color);
    if (attributes.style) parts.push(`${attributes.style} style`);
    if (attributes.fit) parts.push(`${attributes.fit} fit`);
    if (attributes.sleeve_length) parts.push(`${attributes.sleeve_length} sleeves`);
    if (attributes.pattern && attributes.pattern !== 'solid') parts.push(`${attributes.pattern} pattern`);
    if (attributes.material) parts.push(`made of ${attributes.material}`);
    
    return parts.join(', ');
  };

  const handleGenerateInstruction = () => {
    const instruction = generateInstruction();
    if (instruction) {
      // Auto-fill the instruction in parent component
      if (onAttributesChange) {
        onAttributesChange({ ...attributes, generated_instruction: instruction });
      }
      return instruction;
    }
    return '';
  };

  return (
    <div className="attributes-form">
      <div className="form-header">
        <h3>
          <Palette size={20} />
          Garment Attributes
        </h3>
        <p className="form-subtitle">Select attributes for precise generation</p>
      </div>

      <div className="attributes-grid">
        {/* Garment Type */}
        <div className="attribute-group">
          <label className="attribute-label">
            <Shirt size={16} />
            Garment Type
          </label>
          <div className="attribute-options">
            {garmentTypes.map((type) => (
              <button
                key={type}
                type="button"
                className={`attribute-option ${attributes.garment_type === type ? 'selected' : ''}`}
                onClick={() => handleChange('garment_type', type)}
              >
                {type}
              </button>
            ))}
          </div>
        </div>

        {/* Color */}
        <div className="attribute-group">
          <label className="attribute-label">
            <Droplets size={16} />
            Color
          </label>
          <div className="color-options">
            {colors.map((color) => (
              <button
                key={color}
                type="button"
                className={`color-option ${attributes.color === color ? 'selected' : ''}`}
                onClick={() => handleChange('color', color)}
                title={color}
                style={{ backgroundColor: color }}
              >
                <span className="color-name">{color}</span>
              </button>
            ))}
          </div>
        </div>

        {/* Style */}
        <div className="attribute-group">
          <label className="attribute-label">Style</label>
          <select
            className="attribute-select"
            value={attributes.style}
            onChange={(e) => handleChange('style', e.target.value)}
          >
            <option value="">Select style</option>
            {styles.map((style) => (
              <option key={style} value={style}>
                {style}
              </option>
            ))}
          </select>
        </div>

        {/* Fit */}
        <div className="attribute-group">
          <label className="attribute-label">
            <Ruler size={16} />
            Fit
          </label>
          <div className="attribute-options">
            {fits.map((fit) => (
              <button
                key={fit}
                type="button"
                className={`attribute-option ${attributes.fit === fit ? 'selected' : ''}`}
                onClick={() => handleChange('fit', fit)}
              >
                {fit}
              </button>
            ))}
          </div>
        </div>

        {/* Sleeve Length */}
        <div className="attribute-group">
          <label className="attribute-label">Sleeve Length</label>
          <select
            className="attribute-select"
            value={attributes.sleeve_length}
            onChange={(e) => handleChange('sleeve_length', e.target.value)}
          >
            <option value="">Select sleeve length</option>
            {sleeveLengths.map((length) => (
              <option key={length} value={length}>
                {length}
              </option>
            ))}
          </select>
        </div>

        {/* Pattern */}
        <div className="attribute-group">
          <label className="attribute-label">Pattern</label>
          <select
            className="attribute-select"
            value={attributes.pattern}
            onChange={(e) => handleChange('pattern', e.target.value)}
          >
            <option value="">Select pattern</option>
            {patterns.map((pattern) => (
              <option key={pattern} value={pattern}>
                {pattern}
              </option>
            ))}
          </select>
        </div>

        {/* Material */}
        <div className="attribute-group">
          <label className="attribute-label">Material</label>
          <select
            className="attribute-select"
            value={attributes.material}
            onChange={(e) => handleChange('material', e.target.value)}
          >
            <option value="">Select material</option>
            {materials.map((material) => (
              <option key={material} value={material}>
                {material}
              </option>
            ))}
          </select>
        </div>
      </div>

      {/* Generated Instruction Preview */}
      <div className="instruction-preview">
        <div className="preview-header">
          <h4>Generated Instruction</h4>
          <button
            type="button"
            className="generate-button"
            onClick={handleGenerateInstruction}
          >
            <Zap size={16} />
            Generate
          </button>
        </div>
        <div className="preview-content">
          {generateInstruction() || 'Select attributes to generate instruction...'}
        </div>
      </div>

      {/* Selected Attributes Summary */}
      <div className="selected-attributes">
        <h4>Selected Attributes:</h4>
        <div className="attributes-list">
          {Object.entries(attributes).map(([key, value]) => (
            value && key !== 'generated_instruction' && (
              <span key={key} className="attribute-tag">
                {key}: {value}
              </span>
            )
          ))}
        </div>
      </div>
    </div>
  );
};

export default AttributesForm;