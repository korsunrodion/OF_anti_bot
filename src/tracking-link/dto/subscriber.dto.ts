import { IsDateString, IsNumber, IsString } from 'class-validator';

export class SubscriberDto {
  @IsString()
  id: string;

  @IsString()
  username: string;

  @IsNumber()
  userId: number;

  @IsDateString()
  subscriptionDate: string;
}
