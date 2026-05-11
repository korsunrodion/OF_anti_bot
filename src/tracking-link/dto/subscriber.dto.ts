import { ApiProperty } from '@nestjs/swagger';
import { IsBoolean, IsDateString, IsNumber, IsString } from 'class-validator';

export class SubscriberDto {
  @ApiProperty({ example: '12345' })
  @IsString()
  id: string;

  @ApiProperty({ example: 'john_doe' })
  @IsString()
  username: string;

  @ApiProperty({ example: 987654321 })
  @IsNumber()
  userId: number;

  @ApiProperty({ example: '2024-06-01T12:00:00.000Z' })
  @IsDateString()
  subscriptionDate: string;

  @ApiProperty({ example: 'https://cdn.example.com/avatar.jpg' })
  @IsString()
  avatarUrl: string;

  @ApiProperty({ example: 'https://cdn.example.com/header.jpg' })
  @IsString()
  header: string;

  @ApiProperty({ example: true })
  @IsBoolean()
  isOnlineMatchesSubscription: boolean;

  @ApiProperty({ example: false })
  @IsBoolean()
  isReadingMessages: boolean;
}
