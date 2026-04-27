"""
Data Loaders configuration for DataTypes.
Each loader function should accept a path and any parsed metadata,
and return the loaded data representation intended for plotting/viewing.
"""
import os
import re

def load_physiology(data_file):
    """
    Example loader function for 'physiology' DataType.
    :param data_file: The models.Data object representing the file/folder.
    """
    full_path = os.path.join(data_file.location.base_path, data_file.relative_path)
    
    # Check what kind of data the file holds and load accordingly.
    # For now, it returns a skeleton output.
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"File not found on disk: {full_path}")
        
    return {
        "status": "success",
        "message": f"Loaded physiology data from {full_path}",
        "raw_attributes": {
            "name": data_file.name,
            "associated_animals": [a.custom_id for a in data_file.animals.all()]
        }
    }

def load_noise_exposure(data_file):
    """
    Example loader for noise exposure data that may map to multiple animals.
    """
    full_path = os.path.join(data_file.location.base_path, data_file.relative_path)
    
    if not os.path.exists(full_path):
        raise FileNotFoundError(f"File not found on disk: {full_path}")
        
    return {
        "status": "success",
        "message": f"Loaded noise exposure summary from {full_path}",
        "associated_animals_count": data_file.animals.count()
    }
