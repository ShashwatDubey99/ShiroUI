#!/usr/bin/env python3
"""
Tiny AutoEncoder for Stable Diffusion
(DNN for encoding / decoding SD's latent space)
"""
import torch
import torch.nn as nn
from torchvision.transforms import ToPILImage
import os

import shiro.utils
import shiro.ops


def conv(n_in, n_out, **kwargs):
    return shiro.ops.disable_weight_init.Conv2d(n_in, n_out, 3, padding=1, **kwargs)


class Clamp(nn.Module):
    def forward(self, x):
        return torch.tanh(x / 3) * 3


class Block(nn.Module):
    def __init__(self, n_in, n_out):
        super().__init__()
        self.conv = nn.Sequential(
            conv(n_in, n_out),
            nn.ReLU(),
            conv(n_out, n_out),
            nn.ReLU(),
            conv(n_out, n_out)
        )
        self.skip = shiro.ops.disable_weight_init.Conv2d(n_in, n_out, 1, bias=False) if n_in != n_out else nn.Identity()
        self.fuse = nn.ReLU()

    def forward(self, x):
        return self.fuse(self.conv(x) + self.skip(x))


def Encoder(latent_channels=4):
    return nn.Sequential(
        conv(3, 64), Block(64, 64),
        conv(64, 64, stride=2, bias=False), Block(64, 64), Block(64, 64), Block(64, 64),
        conv(64, 64, stride=2, bias=False), Block(64, 64), Block(64, 64), Block(64, 64),
        conv(64, 64, stride=2, bias=False), Block(64, 64), Block(64, 64), Block(64, 64),
        conv(64, latent_channels),
    )


def Decoder(latent_channels=4):
    return nn.Sequential(
        Clamp(), conv(latent_channels, 64), nn.ReLU(),
        Block(64, 64), Block(64, 64), Block(64, 64), nn.Upsample(scale_factor=2), conv(64, 64, bias=False),
        Block(64, 64), Block(64, 64), Block(64, 64), nn.Upsample(scale_factor=2), conv(64, 64, bias=False),
        Block(64, 64), Block(64, 64), Block(64, 64), nn.Upsample(scale_factor=2), conv(64, 64, bias=False),
        Block(64, 64), conv(64, 3),
    )


class TAESD(nn.Module):
    latent_magnitude = 3
    latent_shift = 0.5

    def __init__(self, encoder_path=None, decoder_path=None, latent_channels=4):
        """Initialize pretrained TAESD on the given device from the given checkpoints."""
        super().__init__()
        self.taesd_encoder = Encoder(latent_channels=latent_channels)
        self.taesd_decoder = Decoder(latent_channels=latent_channels)
        self.vae_scale = torch.nn.Parameter(torch.tensor(1.0))
        self.vae_shift = torch.nn.Parameter(torch.tensor(0.0))
        if encoder_path is not None:
            self.taesd_encoder.load_state_dict(shiro.utils.load_torch_file(encoder_path, safe_load=True))
        if decoder_path is not None:
            self.taesd_decoder.load_state_dict(shiro.utils.load_torch_file(decoder_path, safe_load=True))

    @staticmethod
    def scale_latents(x):
        """raw latents -> [0, 1]"""
        return x.div(2 * TAESD.latent_magnitude).add(TAESD.latent_shift).clamp(0, 1)

    @staticmethod
    def unscale_latents(x):
        """[0, 1] -> raw latents"""
        return x.sub(TAESD.latent_shift).mul(2 * TAESD.latent_magnitude)

    def decode(self, x):
        """
        Decode the latent representation into an image and save it to /tmp/reconstructed_image.jpg.
        """
        x_sample = self.taesd_decoder((x - self.vae_shift) * self.vae_scale)
        x_sample = x_sample.sub(0.5).mul(2)
    
        # Save the image to /tmp/reconstructed_image.jpg
        save_path = "/tmp/reconstructed_image.webp"
        normalized_image = (x_sample + 1) / 2.0  # Normalize to [0, 1]
        normalized_image = torch.clamp(normalized_image, 0, 1)
    
        # Convert the first image in the batch to a PIL image
        pil_image = ToPILImage()(normalized_image[0].cpu())
    
        # Compress and save the image
        os.makedirs(os.path.dirname(save_path), exist_ok=True)  # Ensure directory exists
        pil_image.save(save_path, "WEBP", quality=10)  # Save as a JPEG with low quality (20)
        
    
        return x_sample

    def encode(self, x):
        return (self.taesd_encoder(x * 0.5 + 0.5) / self.vae_scale) + self.vae_shift
